package store

import (
	"context"
	"errors"

	"github.com/jackc/pgx/v5"
)

// postgresTransaction owns only its transaction's targeted rows, never a lexical index.
type postgresTransaction struct {
	ctx context.Context
	tx  pgx.Tx
}

func (p *postgresTransaction) get(id string) (Fact, error) {
	var payload []byte
	var key string
	var version int
	err := p.tx.QueryRow(p.ctx, `SELECT id, version, payload FROM memcue.facts WHERE id=$1 ORDER BY version DESC LIMIT 1`, id).Scan(&key, &version, &payload)
	if errors.Is(err, pgx.ErrNoRows) {
		return Fact{}, ErrNotFound
	}
	if err != nil {
		return Fact{}, errRemote
	}
	var f Fact
	if unmarshalFact(p.ctx, payload, &f) != nil || f.ID != id || key != id || f.Version != version {
		return Fact{}, errRemote
	}
	return f, nil
}
func (p *postgresTransaction) append(facts []Fact) error {
	if len(facts) == 0 {
		return nil
	}
	var n int64
	if err := p.tx.QueryRow(p.ctx, `SELECT count(*) FROM memcue.facts`).Scan(&n); err != nil {
		return errRemote
	}
	if n+int64(len(facts)) > 100000 {
		return errors.New("PostgreSQL history exceeds this client's projection limit")
	}
	for _, f := range facts {
		b, err := marshalFact(p.ctx, f)
		if err != nil {
			return errRemote
		}
		if _, err = p.tx.Exec(p.ctx, `INSERT INTO memcue.facts(id,version,payload) VALUES($1,$2,$3)`, f.ID, f.Version, b); err != nil {
			return errRemote
		}
	}
	var size int64
	if err := p.tx.QueryRow(p.ctx, `SELECT coalesce(sum(octet_length(payload::text)),0) FROM memcue.facts`).Scan(&size); err != nil {
		return errRemote
	}
	if size > 64<<20 {
		return errors.New("PostgreSQL history exceeds this client's projection limit")
	}
	return nil
}
func nativeTransaction[T any](s *Store, write bool, fn func(*postgresTransaction) (T, error)) (result T, err error) {
	ctx, cancel := s.operationContext()
	defer cancel()
	defer func() {
		if err == nil && ctx.Err() != nil {
			var zero T
			result = zero
			if write {
				err = ErrAmbiguous
			} else {
				err = ctx.Err()
			}
		}
	}()
	owned, release := ownedBudgetConfig(ctx, s.remote.config)
	defer release()
	c, err := pgx.ConnectConfig(ctx, owned)
	if err != nil {
		return result, errRemote
	}
	stop := context.AfterFunc(ctx, func() { _ = c.PgConn().Conn().Close() })
	defer stop()
	defer func() { _ = c.Close(ctx) }()
	opts := pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly}
	if write {
		opts = pgx.TxOptions{}
	}
	tx, err := c.BeginTx(ctx, opts)
	if err != nil {
		return result, errRemote
	}
	defer func() { _ = tx.Rollback(ctx) }()
	if write {
		if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(680681)`); err != nil {
			return result, errRemote
		}
	}
	result, err = fn(&postgresTransaction{ctx, tx})
	if err != nil {
		return result, err
	}
	if write {
		if err = tx.Commit(ctx); err != nil {
			return result, ErrAmbiguous
		}
	}
	return result, nil
}
func remoteWrite[T any](s *Store, fn func(*Store) (T, error)) (T, error) {
	result, err := nativeTransaction(s, true, func(p *postgresTransaction) (T, error) { return fn(&Store{native: p, now: s.now, author: s.author}) })
	s.remote.mu.Lock()
	if s.remote.projection != nil {
		_ = s.remote.projection.Close()
		s.remote.projection = nil
	}
	s.remote.mu.Unlock()
	return result, err
}
func remoteRead(s *Store, id string, _ bool) (Fact, error) {
	return nativeTransaction(s, false, func(p *postgresTransaction) (Fact, error) { return p.get(id) })
}
func remoteHistory(s *Store, id string) ([]Fact, error) { return remoteVersions(s, id, true) }
func remoteRows(s *Store) ([]Fact, error)               { return remoteVersions(s, "", false) }
func remoteVersions(s *Store, id string, targeted bool) ([]Fact, error) {
	return nativeTransaction(s, false, func(p *postgresTransaction) ([]Fact, error) {
		q := `SELECT id, version, payload FROM memcue.facts ORDER BY id,version LIMIT 100001`
		var args []any
		if targeted {
			q = `SELECT id, version, payload FROM memcue.facts WHERE id=$1 ORDER BY version LIMIT 100001`
			args = []any{id}
		}
		rows, err := p.tx.Query(p.ctx, q, args...)
		if err != nil {
			return nil, errRemote
		}
		defer rows.Close()
		var out []Fact
		size := 0
		for rows.Next() {
			var key string
			var version int
			var b []byte
			if rows.Scan(&key, &version, &b) != nil {
				return nil, errRemote
			}
			size += len(b)
			if len(out) >= 100000 || size > 64<<20 {
				return nil, errRemote
			}
			var f Fact
			if unmarshalFact(p.ctx, b, &f) != nil || f.ID != key || f.Version != version {
				return nil, errRemote
			}
			out = append(out, f)
		}
		if rows.Err() != nil {
			return nil, errRemote
		}
		return out, nil
	})
}
