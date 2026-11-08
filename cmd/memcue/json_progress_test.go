package main

import (
	"context"
	"encoding/json"
	"errors"
	"runtime"
	"strings"
	"testing"
)

// Cancellation is armed only inside the real unknown-field traversal, after
// input framing has completed. No timers or detached workers are involved.
type skipPhaseContext struct {
	context.Context
	observations int
	cancel       context.CancelFunc
}

func (c *skipPhaseContext) Err() error {
	if e := c.Context.Err(); e != nil {
		return e
	}
	pcs := make([]uintptr, 24)
	n := runtime.Callers(2, pcs)
	frames := runtime.CallersFrames(pcs[:n])
	for {
		f, more := frames.Next()
		if strings.Contains(f.Function, "jsonctx.(*factDecoder).skip") {
			c.observations++
			if c.observations >= 3 {
				c.cancel()
				return c.Context.Err()
			}
			return nil
		}
		if !more {
			break
		}
	}
	return nil
}
func TestNativeUnknownJSONCancellation(t *testing.T) {
	for _, value := range []string{"true", "false", "null", "[]", "{}"} {
		t.Run(value, func(t *testing.T) {
			input := `{"unknown":[` + strings.Repeat(value+",", 12000) + `null],"cwd":"bounded-suffix"}`
			var baseline sessionStartInput
			if e := json.Unmarshal([]byte(input), &baseline); e != nil || baseline.CWD != "bounded-suffix" {
				t.Fatal("invalid baseline")
			}
			base, cancel := context.WithCancel(context.Background())
			defer cancel()
			ctx := &skipPhaseContext{Context: base, cancel: cancel}
			inv := &invocation{ctx: ctx, stop: func() {}}
			var got sessionStartInput
			e := inv.decodeInput(strings.NewReader(input), &got)
			if !errors.Is(e, context.Canceled) {
				t.Fatalf("unknown %s traversal did not cancel before suffix: observations=%d err=%v", value, ctx.observations, e)
			}
			if got.CWD != "" {
				t.Fatal("decoder traversed suffix after phase cancellation")
			}
			inv.ctx = context.Background()
			if e = inv.decodeInput(strings.NewReader(input), &got); e != nil || got != baseline {
				t.Fatal("valid unknown-field equivalence changed")
			}
		})
	}
}
