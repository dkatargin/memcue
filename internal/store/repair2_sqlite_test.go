package store

import (
	"context"
	"errors"
	"os"
	"testing"
	"time"
)

func TestRepair2ProjectionSQLUsesRequestCancellation(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	writer, err := OpenPostgres(dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = writer.Close() }()
	if _, err = writer.AddWith("synthetic bounded sqlite", "fixture", "", Meta{}); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	s, err := OpenPostgresContext(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	start := time.Now()
	_, err = remoteDo(s, false, func(local *Store) ([]Fact, error) {
		return local.query(`WITH RECURSIVE work(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM work WHERE n<5000000) SELECT ` + columns + ` FROM facts WHERE (SELECT max(n) FROM work)>0`)
	})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("SQLite did not honor request cancellation: %v", err)
	}
	if time.Since(start) > 400*time.Millisecond {
		t.Fatalf("SQLite CPU work escaped request deadline: %v", time.Since(start))
	}
}
