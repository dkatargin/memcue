package text

import (
	"context"
	"unicode"
)

// EqualContext bounds each equality comparison, including variable-long terms.
func EqualContext(ctx context.Context, a, b string) (bool, error) {
	if e := ctx.Err(); e != nil {
		return false, e
	}
	if len(a) != len(b) {
		return false, nil
	}
	for i := 0; i < len(a); i += 256 {
		if e := ctx.Err(); e != nil {
			return false, e
		}
		end := min(i+256, len(a))
		if a[i:end] != b[i:end] {
			return false, nil
		}
	}
	return true, ctx.Err()
}

func CoversContext(ctx context.Context, term, stem string) (bool, error) {
	p, prefix := Prefix(term) // Prefix examines at most six runes and one final rune.
	if prefix {
		if len(stem) < len(p) {
			return false, ctx.Err()
		}
		stem = stem[:len(p)]
	}
	return EqualContext(ctx, p, stem)
}

func IsTicketContext(ctx context.Context, term string) (bool, error) {
	if e := ctx.Err(); e != nil {
		return false, e
	}
	if len(term) < 3 || term[:2] != "tk" || term[len(term)-1] < '0' || term[len(term)-1] > '9' {
		return false, nil
	}
	for i := 2; i < len(term); i++ {
		if i%256 == 0 {
			if e := ctx.Err(); e != nil {
				return false, e
			}
		}
		c := term[i]
		if (c < 'a' || c > 'z') && (c < '0' || c > '9') {
			return false, nil
		}
	}
	return true, ctx.Err()
}

func IsNumberTermContext(ctx context.Context, term string) (bool, error) {
	if e := ctx.Err(); e != nil {
		return false, e
	}
	if len(term) < 2 || term[:2] != "nm" {
		return false, nil
	}
	digit := false
	n := 0
	for _, r := range term[2:] {
		n++
		if n%256 == 0 {
			if e := ctx.Err(); e != nil {
				return false, e
			}
		}
		switch {
		case unicode.IsDigit(r):
			digit = true
		case unicode.IsLetter(r), r == 'x':
		default:
			return false, nil
		}
	}
	return digit, ctx.Err()
}
