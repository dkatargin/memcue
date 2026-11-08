package main

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/juev/memcue/internal/store"
)

func TestBatchCommittedReceiptLossIsUnknown(t *testing.T) {
	dsn := os.Getenv("MEMCUE_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	t.Setenv("MEMCUE_POSTGRES_DSN", dsn)
	input := filepath.Join(t.TempDir(), "batch.json")
	if e := os.WriteFile(input, []byte(`[{"content":"Prefer clear batch reviews.","source":"user"},{"content":"Prefer concrete batch examples.","source":"user"}]`), 0600); e != nil {
		t.Fatal(e)
	}
	inv := &invocation{ctx: context.Background(), stop: func() {}}
	e := inv.runAddBatch(input, false, lostReceiptWriter{})
	s, e2 := store.OpenPostgresRequest(dsn, 4*time.Second)
	if e2 != nil {
		t.Fatal(e2)
	}
	defer func() { _ = s.Close() }()
	rows, e2 := s.Rows()
	if e2 != nil {
		t.Fatal(e2)
	}
	count := 0
	for _, f := range rows {
		if strings.Contains(f.Content, "batch") {
			count++
		}
	}
	if count != 2 {
		t.Fatalf("real committed batch precondition count=%d", count)
	}
	if e == nil || !strings.Contains(e.Error(), "UNKNOWN OUTCOME") {
		t.Fatalf("batch receipt loss must report UNKNOWN OUTCOME: %v", e)
	}
}
