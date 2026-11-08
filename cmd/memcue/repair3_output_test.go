package main

import (
	"context"
	"errors"
	"github.com/juev/memcue/internal/store"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestRepair3OutputBackpressureCancellation(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "facts.db")
	t.Setenv("MEMCUE_FACTS", path)
	t.Setenv("MEMCUE_POSTGRES_DSN", "")
	s, e := store.Open(path)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.AddWith(strings.Repeat("orchard ", 16384), "fixture", "", store.Meta{Source: "user"}); e != nil {
		t.Fatal(e)
	}
	_ = s.Close()
	r, w, e := os.Pipe()
	if e != nil {
		t.Fatal(e)
	}
	defer func() { _ = r.Close(); _ = w.Close() }()
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()
	inv := &invocation{ctx: ctx, stop: cancel}
	done := make(chan struct{})
	go func() { time.Sleep(350 * time.Millisecond); _ = r.Close(); close(done) }()
	start := time.Now()
	e = inv.runFacts(w)
	elapsed := time.Since(start)
	<-done
	if !errors.Is(e, context.DeadlineExceeded) || elapsed > 250*time.Millisecond {
		t.Fatalf("native output backpressure escaped request: %s %v", elapsed, e)
	}
}
