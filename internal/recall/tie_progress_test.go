package recall

import (
	"context"
	"errors"
	"runtime"
	"strings"
	"testing"

	"github.com/juev/memcue/internal/store"
)

type tieProgressContext struct {
	context.Context
	cancel       context.CancelFunc
	phase        string
	observations int
}

func (c *tieProgressContext) Err() error {
	if e := c.Context.Err(); e != nil {
		return e
	}
	pcs := make([]uintptr, 32)
	n := runtime.Callers(2, pcs)
	frames := runtime.CallersFrames(pcs[:n])
	phase, sort := false, false
	for {
		f, more := frames.Next()
		phase = phase || strings.Contains(f.Function, c.phase)
		sort = sort || strings.Contains(f.Function, "recall.sortStableContext")
		if !more {
			break
		}
	}
	if phase && sort {
		c.observations++
		if c.observations == 8 {
			c.cancel()
		}
	}
	return c.Context.Err()
}
func TestNativeTieComparatorCancellationAfterProgress(t *testing.T) {
	for _, phase := range []string{"recall.foldEqualContext", "recall.projectPlaceContext"} {
		t.Run(phase, func(t *testing.T) {
			s := emptyBase(t)
			host := strings.Repeat("Ж", 8192)
			var project []string
			if strings.Contains(phase, "project") {
				host = ""
				for i := 0; i < 64; i++ {
					project = append(project, strings.Repeat("p", 128)+string(rune('A'+i)))
				}
				project = append(project, "repo/target")
			}
			for i, scope := range []string{"host:" + strings.ToLower(host), "global", ""} {
				origin := "fixture"
				if i == 2 {
					origin = "repo/target 2026-11-08"
				}
				if _, e := s.AddWith("synthetic caddy config reload", origin, "", store.Meta{Scope: scope}); e != nil {
					t.Fatal(e)
				}
			}
			q := Query{Text: "caddy", N: 1, Host: host, Project: project, In: []string{"all"}, MinScore: MinScore}
			positive, e := Search(s, q)
			if e != nil || len(positive) != 1 {
				t.Fatal("native tie precondition")
			}
			base, cancel := context.WithCancel(context.Background())
			defer cancel()
			ctx := &tieProgressContext{Context: base, cancel: cancel, phase: phase}
			s.BindLocalContext(ctx)
			_, e = Search(s, q)
			if !errors.Is(e, context.Canceled) || ctx.observations != 8 {
				t.Fatalf("native comparator did not cancel within finite work: phase=%s progress=%d err=%v", phase, ctx.observations, e)
			}
			select {
			case <-ctx.Done():
			default:
				t.Fatal("real cancellation must close Done")
			}
		})
	}
}
