package text

import (
	"context"
	ce "github.com/juev/memcue/internal/text/snowcontext/english"
	cr "github.com/juev/memcue/internal/text/snowcontext/russian"
	"unicode"
)

// StemsContext preserves ordinary/ticket/numeric order and checks cancellation
// while scanning and between bounded whitespace-delimited lexical batches.
func StemsContext(ctx context.Context, s string) ([]string, error) {
	words, tickets, numbers, err := wordPartsContext(ctx, s)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, group := range [][]string{words, tickets, numbers} {
		for _, w := range group {
			st, ok, e := stemContext(ctx, w)
			if e != nil {
				return nil, e
			}
			if ok {
				out = append(out, st)
			}
		}
	}
	return out, ctx.Err()
}

func stemContext(ctx context.Context, w string) (string, bool, error) {
	if err := ctx.Err(); err != nil {
		return "", false, err
	}
	if len(w) <= 256 {
		st, ok := stem(w)
		return st, ok, ctx.Err()
	}
	cyr, lat, digits, n := 0, 0, 0, 0
	allDigits := true
	for _, r := range w {
		n++
		if n%256 == 0 {
			if err := ctx.Err(); err != nil {
				return "", false, err
			}
		}
		if !unicode.IsDigit(r) {
			allDigits = false
		}
		switch {
		case r >= 'а' && r <= 'я':
			cyr++
		case r >= 'a' && r <= 'z':
			lat++
		case unicode.IsDigit(r):
			digits++
		}
	}
	if allDigits {
		return "", false, ctx.Err()
	}
	switch {
	case cyr > 0 && lat == 0 && digits == 0:
		st, e := cr.Stem(ctx, w, false)
		return st, cyr >= 2, e
	case lat > 0 && cyr == 0 && digits == 0:
		st, e := ce.Stem(ctx, w, false)
		return st, lat >= 2, e
	case digits > 0 && cyr+lat > 0:
		return w, true, ctx.Err()
	}
	return "", false, ctx.Err()
}

// TermsContext uses the same lexer and prompt-stop rules as Terms, with the
// invocation lifetime carried into every lexical/stemming unit.
func TermsContext(ctx context.Context, s string) ([]string, error) {
	a, b, c, e := wordPartsContext(ctx, s)
	if e != nil {
		return nil, e
	}
	seen := map[string]bool{}
	var out []string
	for _, group := range [][]string{a, b, c} {
		for _, w := range group {
			if e = ctx.Err(); e != nil {
				return nil, e
			}
			if len(w) <= 256 && promptStop[w] {
				continue
			}
			st, ok, e := stemContext(ctx, w)
			if e != nil {
				return nil, e
			}
			if !ok || seen[st] || len(st) <= 256 && promptStopStems[st] {
				continue
			}
			seen[st] = true
			out = append(out, st)
		}
	}
	return out, ctx.Err()
}
