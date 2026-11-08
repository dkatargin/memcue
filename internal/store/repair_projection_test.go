package store

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5"
	"os"
	"testing"
	"time"
)

func TestRepairProjectionCannotPublishAfterDeadline(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	s, err := OpenPostgres(dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	c, err := pgx.Connect(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close(context.Background()) }()
	if _, err = c.Exec(context.Background(), "TRUNCATE memcue.facts"); err != nil {
		t.Fatal(err)
	}
	f, err := s.AddWith("synthetic projection budget", "fixture", "", Meta{})
	if err != nil {
		t.Fatal(err)
	}
	_, err = remoteDo(s, false, func(local *Store) (Fact, error) { time.Sleep(10100 * time.Millisecond); return local.Get(f.ID) })
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expired projection published success instead of operation deadline: %v", err)
	}
}
