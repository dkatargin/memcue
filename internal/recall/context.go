package recall

import (
	"context"
	"github.com/juev/memcue/internal/store"
	"github.com/juev/memcue/internal/text"
	"github.com/juev/memcue/internal/tier"
	"sort"
	"strings"
	"unicode"
	"unicode/utf8"
)

type sortCancelled struct{ err error }

func sortStableContext(ctx context.Context, items any, less func(int, int) bool) (err error) {
	if err = ctx.Err(); err != nil {
		return err
	}
	defer func() {
		if v := recover(); v != nil {
			if c, ok := v.(sortCancelled); ok {
				err = c.err
			} else {
				panic(v)
			}
		}
	}()
	n := 0
	sort.SliceStable(items, func(i, j int) bool {
		n++
		if n%64 == 0 {
			if e := ctx.Err(); e != nil {
				panic(sortCancelled{e})
			}
		}
		return less(i, j)
	})
	return ctx.Err()
}

func holdsContext(ctx context.Context, terms, stems []string) (int, error) {
	n, checks := 0, 0
	for _, t := range terms {
		for _, st := range stems {
			checks++
			if checks%64 == 0 {
				if e := ctx.Err(); e != nil {
					return 0, e
				}
			}
			covered, e := text.CoversContext(ctx, t, st)
			if e != nil {
				return 0, e
			}
			if covered {
				n++
				break
			}
		}
	}
	return n, ctx.Err()
}

func containsContext(ctx context.Context, values []string, target string) (bool, error) {
	for _, v := range values {
		ok, e := text.EqualContext(ctx, v, target)
		if e != nil {
			return false, e
		}
		if ok {
			return true, nil
		}
	}
	return false, ctx.Err()
}

// Compare fold cycles rune by rune, rather than allocating a lower-cased host.
// EqualFold permits different UTF-8 lengths (for example K and Kelvin sign).
func foldEqualContext(ctx context.Context, a string, parts ...string) (bool, error) {
	pos, work := 0, 0
	for _, part := range parts {
		for len(part) > 0 {
			if pos == len(a) {
				return false, ctx.Err()
			}
			ar, an := utf8.DecodeRuneInString(a[pos:])
			br, bn := utf8.DecodeRuneInString(part)
			if ar != br {
				r := unicode.SimpleFold(ar)
				for r != ar && r != br {
					r = unicode.SimpleFold(r)
				}
				if r != br {
					return false, ctx.Err()
				}
			}
			pos += an
			part = part[bn:]
			work += an + bn
			if work >= 256 {
				if e := ctx.Err(); e != nil {
					return false, e
				}
				work = 0
			}
		}
	}
	return pos == len(a), ctx.Err()
}
func projectPlaceContext(ctx context.Context, origin string, project []string) (bool, error) {
	for _, key := range project {
		if key != "" && len(origin) > len(key) && origin[len(key)] == ' ' {
			yes, e := text.EqualContext(ctx, origin[:len(key)], key)
			if e != nil || yes {
				return yes, e
			}
		}
		if e := ctx.Err(); e != nil {
			return false, e
		}
	}
	return false, ctx.Err()
}
func placeContext(ctx context.Context, h store.Fact, project []string, host string) (int, error) {
	if host != "" {
		yes, e := foldEqualContext(ctx, h.Scope, "host:", host)
		if e != nil {
			return 0, e
		}
		if yes {
			return 0, nil
		}
	}
	yes, e := projectPlaceContext(ctx, h.Origin, project)
	if e != nil {
		return 0, e
	}
	if yes {
		return 1, nil
	}
	if strings.HasPrefix(h.Origin, tier.Global+" ") {
		return 2, ctx.Err()
	}
	return 3, ctx.Err()
}
func mustPlace(ctx context.Context, h store.Fact, project []string, host string) int {
	p, e := placeContext(ctx, h, project, host)
	if e != nil {
		panic(sortCancelled{e})
	}
	return p
}
func newerContext(ctx context.Context, a, b store.Fact) bool {
	if !a.Created.Equal(b.Created) {
		return a.Created.After(b.Created)
	}
	x, y := a.ID, b.ID
	for len(x) > 0 && len(y) > 0 {
		n := min(256, len(x), len(y))
		c := strings.Compare(x[:n], y[:n])
		if e := ctx.Err(); e != nil {
			panic(sortCancelled{e})
		}
		if c != 0 {
			return c > 0
		}
		x = x[n:]
		y = y[n:]
	}
	return len(x) > len(y)
}
