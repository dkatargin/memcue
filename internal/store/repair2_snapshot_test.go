package store

import (
	"context"
	"github.com/jackc/pgx/v5"
	"os"
	"testing"
	"time"
)

func TestRepair2RequestQuerySnapshot(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	writer, err := OpenPostgres(dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = writer.Close() }()
	c, err := pgx.Connect(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close(context.Background()) }()
	if _, err = c.Exec(context.Background(), "TRUNCATE memcue.facts"); err != nil {
		t.Fatal(err)
	}
	first, err := writer.AddWith("synthetic cedar PROJ-680", "fixture", "", Meta{Scope: "repo:first", Evidence: "unchanged evidence"})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	request, err := OpenPostgresContext(ctx, dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = request.Close() }()
	if _, err = request.RepoScopes(); err != nil {
		t.Fatal(err)
	} // Lazily captures the query snapshot.
	if _, err = writer.AddWith("synthetic maple", "fixture", "", Meta{Scope: "repo:later"}); err != nil {
		t.Fatal(err)
	}
	current, err := request.Current()
	if err != nil {
		t.Fatal(err)
	}
	if len(current) != 1 || current[0] != first {
		t.Fatalf("query methods did not reuse one request snapshot: got %d facts", len(current))
	}
	if _, err = request.Correct(first.ID, "synthetic revised cedar", first.Version); err != nil {
		t.Fatal(err)
	}
	current, err = request.Current()
	if err != nil {
		t.Fatal(err)
	}
	if len(current) != 2 {
		t.Fatalf("mutation did not invalidate request projection: %d", len(current))
	}
}
