package main

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/jackc/pgx/v5"
	"github.com/juev/memcue/internal/store"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRepairRemoteCLIAtomicBatch(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_CLI_DSN")
	if dsn == "" {
		dsn = os.Getenv("MEMCUE_REPAIR_DSN")
	}
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	t.Setenv("MEMCUE_POSTGRES_DSN", dsn)
	t.Setenv("MEMCUE_TAILSCALE_MODE", "off")
	s, err := store.OpenPostgres(dsn)
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
	inputs := []store.FactInput{{Content: "Synthetic batch cedar", Meta: store.Meta{Source: "user", Scope: "repo:batch", Evidence: "synthetic"}}, {Content: "Synthetic batch birch", Expires: "2099-01-01", Meta: store.Meta{Source: "user", Scope: "shelf:research"}}}
	data, _ := json.Marshal(inputs)
	file := filepath.Join(t.TempDir(), "batch.json")
	if err := os.WriteFile(file, data, 0600); err != nil {
		t.Fatal(err)
	}
	var out bytes.Buffer
	if err := runAdd([]string{"-batch", file}, &out); err != nil {
		t.Fatalf("native add must accept an atomic remote batch: %v", err)
	}
	ids := strings.Fields(out.String())
	if len(ids) != 2 {
		t.Fatalf("batch returned %d IDs", len(ids))
	}
	for i, id := range ids {
		got, err := s.Get(id)
		if err != nil || got.Content != inputs[i].Content || got.Scope != inputs[i].Scope || got.Expires != inputs[i].Expires {
			t.Fatalf("batch metadata roundtrip: %#v %v", got, err)
		}
	}
	inputs[1].Content = " "
	data, _ = json.Marshal(inputs)
	if err := os.WriteFile(file, data, 0600); err != nil {
		t.Fatal(err)
	}
	out.Reset()
	if err := runAdd([]string{"-batch", file}, &out); err == nil {
		t.Fatal("invalid batch accepted")
	}
	var n int
	if err := c.QueryRow(context.Background(), "select count(*) from memcue.facts").Scan(&n); err != nil || n != 2 {
		t.Fatalf("invalid batch partially committed: %d %v", n, err)
	}
}
