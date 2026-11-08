package tailnet_test

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/juev/memcue/internal/store"
	"github.com/juev/memcue/internal/tailnet"
	"net/url"
	"os"
	"testing"
	"time"
)

// A real PostgreSQL query is observed in PgSleep before issuing the real pgconn
// cancellation connection over the same embedded transport and selected peer.
func repairRealCancel(t *testing.T, ctx context.Context, dsn string) {
	t.Helper()
	cfg, err := store.PostgresConfig(dsn)
	if err != nil {
		t.Fatal("isolated database configuration failed")
	}
	if err := tailnet.Configure(ctx, cfg); err != nil {
		t.Fatal(err)
	}
	query, err := pgx.ConnectConfig(ctx, cfg)
	if err != nil {
		t.Fatal("embedded cancellation connection failed")
	}
	defer func() { _ = query.Close(ctx) }()
	adminURL := (&url.URL{Scheme: "postgres", User: url.User("fixture"), Host: os.Getenv("MEMCUE_TEST_POSTGRES_ADDR"), Path: "/postgres", RawQuery: "sslmode=disable&passfile=/dev/null"}).String()
	admin, err := pgx.Connect(ctx, adminURL)
	if err != nil {
		t.Fatal("isolated cancellation observer failed")
	}
	defer func() { _ = admin.Close(ctx) }()
	done := make(chan error, 1)
	go func() { _, err := query.Exec(ctx, "select pg_sleep(5) /* synthetic-cancel */"); done <- err }()
	for {
		var sleeping bool
		err := admin.QueryRow(ctx, "select state='active' and coalesce(wait_event,'')='PgSleep' from pg_stat_activity where pid=$1", query.PgConn().PID()).Scan(&sleeping)
		if err != nil {
			t.Fatal("query opportunity observer failed")
		}
		if sleeping {
			break
		}
		select {
		case err := <-done:
			t.Fatalf("query ended before cancellation opportunity: %v", err)
		case <-ctx.Done():
			t.Fatal("query never reached PgSleep")
		case <-time.After(10 * time.Millisecond):
		}
	}
	start := time.Now()
	if err := query.PgConn().CancelRequest(ctx); err != nil {
		t.Fatalf("actual embedded cancellation delivery: %v", err)
	}
	select {
	case err := <-done:
		var pgErr *pgconn.PgError
		if !errors.As(err, &pgErr) || pgErr.Code != "57014" {
			t.Fatalf("expected PostgreSQL query-canceled response, got %T", err)
		}
	case <-ctx.Done():
		t.Fatal("server did not cancel sleeping query")
	}
	t.Logf("actual PostgreSQL embedded cancel delivered in %s", time.Since(start))
}
