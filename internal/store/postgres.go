package store

import (
	"context"
	"errors"
	"net"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/juev/memcue/internal/tailnet"
)

var errRemote = errors.New("PostgreSQL operation failed; check server availability, permissions and schema")

// ErrAmbiguous means a commit reply was lost. Never automatically replay this mutation.
var ErrAmbiguous = errors.New("PostgreSQL commit outcome is unknown; inspect history before retrying")

type postgresStore struct {
	config     *pgx.ConnConfig
	request    context.Context
	cancel     context.CancelFunc
	mu         sync.Mutex
	projection *Store
}

func PostgresConfig(dsn string) (*pgx.ConnConfig, error) {
	invalid := errors.New("invalid MEMCUE_POSTGRES_DSN: use an explicit single-host PostgreSQL URL with user, database, port and sslmode=verify-full or disable")
	for _, e := range os.Environ() {
		if strings.HasPrefix(e, "PG") {
			return nil, errors.New("ambient PG variables are not supported with MEMCUE_POSTGRES_DSN; unset them")
		}
	}
	u, err := url.Parse(dsn)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.User == nil || u.User.Username() == "" || u.Hostname() == "" || u.Port() == "" || u.Path == "" || u.Path == "/" || strings.Contains(u.Host, ",") || u.Fragment != "" {
		return nil, invalid
	}
	q, err := url.ParseQuery(u.RawQuery)
	if err != nil {
		return nil, invalid
	}
	if q.Get("sslmode") != "verify-full" && q.Get("sslmode") != "disable" {
		return nil, invalid
	}
	for k, v := range q {
		switch k {
		case "sslmode", "sslrootcert", "sslcert", "sslkey", "connect_timeout", "application_name":
		default:
			return nil, invalid
		}
		if len(v) != 1 {
			return nil, invalid
		}
	}
	// pgx otherwise discovers ~/.pgpass, even with a fully explicit endpoint.
	q.Set("passfile", "/dev/null")
	q.Set("connect_timeout", "10")
	u.RawQuery = q.Encode()
	cfg, err := pgx.ParseConfig(u.String())
	if err != nil || len(cfg.Fallbacks) != 0 || strings.HasPrefix(cfg.Host, "/") {
		return nil, invalid
	}
	cfg.RuntimeParams["application_name"] = "memcue"
	cfg.RuntimeParams["statement_timeout"] = "10000"
	cfg.RuntimeParams["lock_timeout"] = "10000"
	return cfg, nil
}

// budgetConfig also constrains pgx's asynchronous cancellation connections, which
// otherwise use a fresh background cleanup context after the caller has returned.
type operationConn struct {
	net.Conn
	once sync.Once
	err  error
}

func (c *operationConn) Close() error { c.once.Do(func() { c.err = c.Conn.Close() }); return c.err }

func budgetConfig(operation context.Context, config *pgx.ConnConfig) *pgx.ConnConfig {
	cfg, _ := ownedBudgetConfig(operation, config)
	return cfg
}

// Each operation owns every connection allocated by its dialer, including pgx's
// independently-contexted asynchronous CancelRequest streams. Shared transports
// are not closed: only the net.Conn returned for this operation is owned here.
func ownedBudgetConfig(operation context.Context, config *pgx.ConnConfig) (*pgx.ConnConfig, func()) {
	cfg := config.Copy()
	dial := cfg.DialFunc
	var mu sync.Mutex
	closed := false
	var connections []*operationConn
	release := func() {
		mu.Lock()
		closed = true
		owned := append([]*operationConn(nil), connections...)
		mu.Unlock()
		for _, c := range owned {
			_ = c.Close()
		}
	}
	stop := context.AfterFunc(operation, release)
	cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
		if err := operation.Err(); err != nil {
			return nil, err
		}
		bounded, cancel := context.WithCancel(ctx)
		defer cancel()
		stopDial := context.AfterFunc(operation, cancel)
		defer stopDial()
		if deadline, ok := operation.Deadline(); ok {
			var clipped context.CancelFunc
			bounded, clipped = context.WithDeadline(bounded, deadline)
			defer clipped()
		}
		conn, err := dial(bounded, network, address)
		if err != nil {
			return nil, err
		}
		owned := &operationConn{Conn: conn}
		mu.Lock()
		if closed || operation.Err() != nil {
			mu.Unlock()
			_ = owned.Close()
			return nil, context.Canceled
		}
		connections = append(connections, owned)
		mu.Unlock()
		return owned, nil
	}
	return cfg, func() { stop(); release() }
}

// OpenPostgres uses PostgreSQL as the sole authority. SQLite projections are private,
// temporary in-memory query engines, never a fallback or a writable local cache.
func OpenPostgres(dsn string) (*Store, error) { return openPostgres(context.Background(), dsn) }
func openPostgres(parent context.Context, dsn string) (*Store, error) {
	cfg, err := PostgresConfig(dsn)
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(parent, 10*time.Second)
	defer cancel()
	if err := tailnet.Configure(ctx, cfg); err != nil {
		return nil, err
	}
	owned, release := ownedBudgetConfig(ctx, cfg)
	defer release()
	c, err := pgx.ConnectConfig(ctx, owned)
	if err != nil {
		return nil, errRemote
	}
	forceClose := context.AfterFunc(ctx, func() { _ = c.PgConn().Conn().Close() })
	defer forceClose()
	defer func() { _ = c.Close(ctx) }()
	tx, err := c.Begin(ctx)
	if err != nil {
		return nil, errRemote
	}
	defer func() { _ = tx.Rollback(ctx) }()

	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(680681)`); err != nil {
		return nil, errRemote
	}
	var versionTable, factsTable bool
	if err = tx.QueryRow(ctx, `SELECT to_regclass('memcue.version') IS NOT NULL,to_regclass('memcue.facts') IS NOT NULL`).Scan(&versionTable, &factsTable); err != nil {
		return nil, errRemote
	}
	if versionTable != factsTable {
		return nil, errors.New("incompatible PostgreSQL schema; operator repair required")
	}
	if !versionTable {
		_, err = tx.Exec(ctx, `CREATE SCHEMA IF NOT EXISTS memcue;
 CREATE TABLE IF NOT EXISTS memcue.version (singleton boolean PRIMARY KEY CHECK(singleton), version integer NOT NULL);
 INSERT INTO memcue.version VALUES(true,1) ON CONFLICT DO NOTHING;
 CREATE TABLE IF NOT EXISTS memcue.facts (id text NOT NULL, version integer NOT NULL CHECK(version>0), payload jsonb NOT NULL, PRIMARY KEY(id,version));`)
		if err != nil {
			return nil, errRemote
		}
	}
	var version int
	if err := tx.QueryRow(ctx, `SELECT version FROM memcue.version WHERE singleton`).Scan(&version); err != nil {
		return nil, errRemote
	}
	if version != 1 {
		return nil, errors.New("incompatible PostgreSQL schema; update Memcue")
	}
	if err := tx.Commit(ctx); err != nil {
		return nil, ErrAmbiguous
	}
	host, _ := os.Hostname()
	return &Store{remote: &postgresStore{config: cfg}, author: host, now: time.Now}, nil
}

// remoteDo builds a current-version query projection lazily. Explicit request
// stores retain one immutable query snapshot; ordinary library stores refresh it
// for each call. History is always read directly from PostgreSQL.
func remoteDo[T any](s *Store, write bool, fn func(*Store) (T, error)) (zero T, err error) {
	if write {
		return zero, ErrRemoteUnsupported
	}
	r := s.remote
	r.mu.Lock()
	defer r.mu.Unlock()
	if r.request != nil && r.request.Err() != nil {
		return zero, r.request.Err()
	}
	if r.projection != nil {
		result, err := fn(r.projection)
		if r.request.Err() != nil {
			return zero, r.request.Err()
		}
		return result, err
	}
	var local *Store
	result, err := nativeTransaction(s, false, func(p *postgresTransaction) (T, error) {
		var e error
		local, e = buildQueryProjection(p)
		if e != nil {
			return zero, e
		}
		local.author, local.now = s.author, s.now
		return fn(local)
	})
	if local != nil {
		if err == nil && r.request != nil {
			local.ctx = r.request
			r.projection = local
		} else {
			_ = local.Close()
		}
	}
	return result, err
}
func buildQueryProjection(p *postgresTransaction) (*Store, error) {
	rows, err := p.tx.Query(p.ctx, `SELECT DISTINCT ON (id) id, version, payload FROM memcue.facts ORDER BY id,version DESC LIMIT 100001`)
	if err != nil {
		return nil, errRemote
	}
	defer rows.Close()
	local, err := openFile(":memory:")
	if err != nil {
		return nil, errRemote
	}
	ok := false
	defer func() {
		if !ok {
			_ = local.Close()
		}
	}()
	local.ctx = p.ctx
	tx, err := local.db.BeginTx(p.ctx, nil)
	if err != nil {
		return nil, errRemote
	}
	defer func() { _ = tx.Rollback() }()
	n, size := 0, 0
	for rows.Next() {
		if p.ctx.Err() != nil {
			return nil, p.ctx.Err()
		}
		var id string
		var version int
		var b []byte
		if rows.Scan(&id, &version, &b) != nil {
			return nil, errRemote
		}
		n++
		size += len(b)
		if n > 100000 || size > 64<<20 {
			return nil, errors.New("PostgreSQL history exceeds this client's projection limit")
		}
		var f Fact
		if unmarshalFact(p.ctx, b, &f) != nil || f.ID != id || f.Version != version {
			return nil, errRemote
		}
		if err = insertContext(p.ctx, tx, f); err != nil {
			return nil, errRemote
		}
	}
	if rows.Err() != nil {
		return nil, errRemote
	}
	if p.ctx.Err() != nil {
		return nil, p.ctx.Err()
	}
	if err = rebuildContext(p.ctx, tx); err != nil {
		return nil, errRemote
	}
	if err = tx.Commit(); err != nil {
		return nil, errRemote
	}
	ok = true
	return local, nil
}

// ErrRemoteUnsupported identifies operations that require a local file or a local maintenance workflow.
var ErrRemoteUnsupported = errors.New("operation unavailable for PostgreSQL; use PostgreSQL backup tools or explicitly unset MEMCUE_POSTGRES_DSN for local maintenance")

// OpenPostgresContext shares one query snapshot until a mutation or Close.
// The caller owns the request context. OpenPostgres retains per-call library semantics.
func OpenPostgresContext(ctx context.Context, dsn string) (*Store, error) {
	s, err := openPostgres(ctx, dsn)
	if err == nil {
		s.remote.request = ctx
	}
	return s, err
}

func (s *Store) operationContext() (context.Context, context.CancelFunc) {
	parent := context.Background()
	if s.remote.request != nil {
		parent = s.remote.request
	}
	return context.WithTimeout(parent, 10*time.Second)
}

// OpenPostgresRequest owns a finite invocation context, including schema startup.
// Close cancels it; callers needing their own context use OpenPostgresContext.
func OpenPostgresRequest(dsn string, budget time.Duration) (*Store, error) {
	if budget <= 0 || budget > 10*time.Second {
		return nil, errors.New("invalid PostgreSQL request budget")
	}
	ctx, cancel := context.WithTimeout(context.Background(), budget)
	s, err := OpenPostgresContext(ctx, dsn)
	if err != nil {
		cancel()
		return nil, err
	}
	s.remote.cancel = cancel
	return s, nil
}
