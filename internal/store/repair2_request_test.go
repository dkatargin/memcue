package store

import (
	"context"
	"os"
	"testing"
	"time"
)

func TestRepair2OneRequestBudget(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 350*time.Millisecond)
	defer cancel()
	s, err := OpenPostgresContext(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	sleep := func(p *postgresTransaction) (int, error) {
		_, err := p.tx.Exec(p.ctx, `SELECT pg_sleep(0.2)`)
		return 0, err
	}
	if _, err = nativeTransaction(s, false, sleep); err != nil {
		t.Fatalf("first query setup: %v", err)
	}
	start := time.Now()
	_, err = nativeTransaction(s, false, sleep)
	if err == nil {
		t.Error("second operation received a fresh deadline beyond the request budget")
	}
	if time.Since(start) > 250*time.Millisecond {
		t.Error("request cancellation did not bound actual PostgreSQL query")
	}
	if _, err = s.Get("absent"); err == nil {
		t.Error("expired request admitted another read")
	}
	// Ordinary OpenPostgres is a reusable library handle, not a single expiring session.
	library, err := OpenPostgres(dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = library.Close() }()
	for i := 0; i < 2; i++ {
		if _, err = nativeTransaction(library, false, sleep); err != nil {
			t.Fatalf("library operation %d inherited expired request: %v", i, err)
		}
	}
}
