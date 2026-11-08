package snowballword

import (
	"context"
	"strings"
	"unicode"
)

type stopped struct{ err error }

// Cancellation unwinds only this synchronous algorithm; it owns no goroutine.
func Recover(err *error) {
	if v := recover(); v != nil {
		if s, ok := v.(stopped); ok {
			*err = s.err
		} else {
			panic(v)
		}
	}
}
func (w *SnowballWord) Check() {
	w.ticks++
	if w.ticks%256 == 0 {
		if err := w.ctx.Err(); err != nil {
			panic(stopped{err})
		}
	}
}
func (w *SnowballWord) encode(rs []rune) string {
	var b strings.Builder
	for _, r := range rs {
		w.Check()
		b.WriteRune(r)
	}
	return b.String()
}
func Normalize(ctx context.Context, s string) string {
	var b strings.Builder
	started := false
	end := 0
	n := 0
	for _, r := range s {
		n++
		if n%256 == 0 {
			if err := ctx.Err(); err != nil {
				panic(stopped{err})
			}
		}
		if !started && unicode.IsSpace(r) {
			continue
		}
		started = true
		b.WriteRune(unicode.ToLower(r))
		if !unicode.IsSpace(r) {
			end = b.Len()
		}
	}
	if err := ctx.Err(); err != nil {
		panic(stopped{err})
	}
	return b.String()[:end]
}
