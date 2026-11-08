package main

import (
	"github.com/juev/memcue/internal/store"
	"os"
	"testing"
	"time"
)

func TestRepair2CLIStoreKeepsOneBudget(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_CLI_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	t.Setenv("MEMCUE_POSTGRES_DSN", dsn)
	writer, err := store.OpenPostgres(dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = writer.Close() }()
	f, err := writer.AddWith("synthetic CLI lifetime fact", "fixture", "", store.Meta{})
	if err != nil {
		t.Fatal(err)
	}
	s, err := openBase()
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	time.Sleep(4100 * time.Millisecond)
	if _, err = s.Get(f.ID); err == nil {
		t.Fatal("CLI store issued a new operation after its shared recall budget")
	}
}
