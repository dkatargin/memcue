package recall

import (
	"context"
	"errors"
	"path/filepath"
	"runtime"
	"strings"
	"testing"

	"github.com/juev/memcue/internal/store"
)

type recallPhaseContext struct {
	context.Context
	all    []string
	count  int
	cancel context.CancelFunc
}

func (c *recallPhaseContext) Err() error {
	if e := c.Context.Err(); e != nil {
		return e
	}
	pcs := make([]uintptr, 32)
	n := runtime.Callers(2, pcs)
	frames := runtime.CallersFrames(pcs[:n])
	found := make([]bool, len(c.all))
	for {
		f, more := frames.Next()
		for i, s := range c.all {
			if strings.Contains(f.Function, s) {
				found[i] = true
			}
		}
		if !more {
			break
		}
	}
	for _, ok := range found {
		if !ok {
			return nil
		}
	}
	c.count++
	if c.count >= 2 {
		c.cancel()
		return c.Context.Err()
	}
	return nil
}
func TestCompleteNativeSearchPhaseCancellation(t *testing.T) {
	s := setup(t)
	q := Query{Text: strings.Repeat("z", 16000) + " caddy config reload path other words more words now", N: 5, MinScore: MinScore}
	if _, e := Search(s, q); e != nil {
		t.Fatal(e)
	}
	base, cancel := context.WithCancel(context.Background())
	defer cancel()
	ctx := &recallPhaseContext{Context: base, cancel: cancel, all: []string{"recall.IsMessage"}}
	s.BindLocalContext(ctx)
	if _, e := Search(s, q); !errors.Is(e, context.Canceled) {
		t.Fatalf("whole-query classification did not cancel inside phase: checks=%d err=%v", ctx.count, e)
	}
}
func TestCompleteNativeContainmentPhaseCancellation(t *testing.T) {
	s, e := store.Open(filepath.Join(t.TempDir(), "facts.db"))
	if e != nil {
		t.Fatal(e)
	}
	defer func() { _ = s.Close() }()
	word := strings.Repeat("ж", 2048) + "ка"
	f, e := s.AddWith(word, "fixture", "", store.Meta{})
	if e != nil {
		t.Fatal(e)
	}
	p := Params{Candidates: 80, MinTerms: 1, MinMatched: 1, MinCoverage: 1.1, MinContained: .8}
	got, e := Recall(s, word, p)
	if e != nil || len(got) != 1 || got[0].ID != f.ID {
		t.Fatalf("containment precondition: count=%d err=%v", len(got), e)
	}
	base, cancel := context.WithCancel(context.Background())
	defer cancel()
	ctx := &recallPhaseContext{Context: base, cancel: cancel, all: []string{"recall.holdsContext", "recall.containedIn"}}
	s.BindLocalContext(ctx)
	if _, e = Recall(s, word, p); !errors.Is(e, context.Canceled) {
		t.Fatalf("long containment comparison did not cancel inside phase: checks=%d err=%v", ctx.count, e)
	}
}

// Supplemental phase coverage after the complete-model repair reached GREEN.
func TestCompleteNativeTicketPhaseCancellation(t *testing.T) {
	s, e := store.Open(filepath.Join(t.TempDir(), "ticket.db"))
	if e != nil {
		t.Fatal(e)
	}
	defer func() { _ = s.Close() }()
	ticket := "PROJ" + strings.Repeat("A", 4096) + "-123"
	if _, e = s.AddWith(ticket, "fixture", "", store.Meta{}); e != nil {
		t.Fatal(e)
	}
	p := Params{Candidates: 80, MinTerms: 1, MinMatched: 1, MinCoverage: .5}
	base, cancel := context.WithCancel(context.Background())
	defer cancel()
	ctx := &recallPhaseContext{Context: base, cancel: cancel, all: []string{"text.IsTicketContext"}}
	s.BindLocalContext(ctx)
	if _, e = Recall(s, ticket, p); !errors.Is(e, context.Canceled) {
		t.Fatalf("native ticket phase: observations=%d err=%v", ctx.count, e)
	}
}
