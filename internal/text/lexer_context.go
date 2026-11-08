package text

import (
	"context"
	"strings"
	"unicode"
	"unicode/utf8"
)

func asciiWord(b byte) bool {
	return b >= 'a' && b <= 'z' || b >= 'A' && b <= 'Z' || b >= '0' && b <= '9' || b == '_'
}
func digit(b byte) bool { return b >= '0' && b <= '9' }
func lexicalCheck(ctx context.Context, i int) error {
	if i%256 == 0 {
		return ctx.Err()
	}
	return nil
}

// The two lexical recognizers implement the pinned regular expressions as
// checkable scans. No token is truncated and no worker outlives the caller.
func wordPartsContext(ctx context.Context, s string) (out, tickets, nums []string, err error) {
	var stripped strings.Builder
	for i := 0; i < len(s); {
		if err = ctx.Err(); err != nil {
			return nil, nil, nil, err
		}
		end := i
		if (s[i] == '#' || s[i] == '!') && i+1 < len(s) && digit(s[i+1]) {
			end = i + 2
			for end < len(s) && digit(s[end]) {
				if err = lexicalCheck(ctx, end); err != nil {
					return
				}
				end++
			}
		} else if s[i] >= 'A' && s[i] <= 'Z' && (i == 0 || !asciiWord(s[i-1])) {
			j := i + 1
			for j < len(s) && (s[j] >= 'A' && s[j] <= 'Z' || digit(s[j])) {
				if err = lexicalCheck(ctx, j); err != nil {
					return
				}
				j++
			}
			if j < len(s) && s[j] == '-' && j+1 < len(s) && digit(s[j+1]) {
				end = j + 2
				for end < len(s) && digit(s[end]) {
					if err = lexicalCheck(ctx, end); err != nil {
						return
					}
					end++
				}
				if end < len(s) && asciiWord(s[end]) {
					end = i
				}
			}
		}
		if end > i {
			var b strings.Builder
			b.WriteString("tk")
			start := i
			switch s[i] {
			case '#':
				b.WriteByte('h')
				start++
			case '!':
				b.WriteByte('b')
				start++
			}
			for j := start; j < end; j++ {
				if err = lexicalCheck(ctx, j); err != nil {
					return
				}
				c := s[j]
				if c == '-' {
					continue
				}
				if c >= 'A' && c <= 'Z' {
					c += 'a' - 'A'
				}
				b.WriteByte(c)
			}
			tickets = append(tickets, b.String())
			stripped.WriteByte(' ')
			i = end
		} else {
			r, n := utf8.DecodeRuneInString(s[i:])
			stripped.WriteRune(r)
			i += n
		}
	}
	var lower strings.Builder
	n := 0
	for _, r := range stripped.String() {
		if err = lexicalCheck(ctx, n); err != nil {
			return
		}
		n++
		r = unicode.ToLower(r)
		if r == 'ё' {
			r = 'е'
		}
		lower.WriteRune(r)
	}
	text := lower.String()
	var ordinary strings.Builder
	for i := 0; i < len(text); {
		if err = ctx.Err(); err != nil {
			return nil, nil, nil, err
		}
		start := i
		if (i == 0 && (digit(text[i]) || text[i] == 'v')) || strings.ContainsRune("\t\n\f\r ([{\"'@:/", rune(text[i])) {
			j := i
			if i != 0 || !digit(text[i]) && text[i] != 'v' {
				j++
			}
			if j < len(text) && text[j] == 'v' {
				j++
			}
			a := j
			for j < len(text) && digit(text[j]) {
				if err = lexicalCheck(ctx, j); err != nil {
					return
				}
				j++
			}
			best := 0
			if j > a {
				for j < len(text) && strings.ContainsRune(".-:/", rune(text[j])) && j+1 < len(text) && digit(text[j+1]) {
					j += 2
					if err = ctx.Err(); err != nil {
						return
					}
					for j < len(text) && digit(text[j]) {
						if err = lexicalCheck(ctx, j); err != nil {
							return
						}
						j++
					}
					if j == len(text) || !asciiWord(text[j]) {
						best = j
					}
				}
			}
			if best > 0 {
				if NumbersEnabled() {
					var b strings.Builder
					b.WriteString("nm")
					k := start
					for k < best && strings.ContainsRune(" \t\n([{\"'@:/", rune(text[k])) {
						k++
					}
					for ; k < best; k++ {
						if err = lexicalCheck(ctx, k); err != nil {
							return
						}
						r := rune(text[k])
						if unicode.IsLetter(r) || unicode.IsDigit(r) {
							b.WriteRune(r)
						} else {
							b.WriteByte('x')
						}
					}
					term := b.String()
					nums = append(nums, term)
				}
				ordinary.WriteByte(' ')
				i = best
				continue
			}
		}
		r, size := utf8.DecodeRuneInString(text[i:])
		ordinary.WriteRune(r)
		i += size
	}
	cleaned := ordinary.String()
	begin := -1
	n = 0
	for i, r := range cleaned {
		if err = lexicalCheck(ctx, n); err != nil {
			return
		}
		n++
		if unicode.IsLetter(r) || unicode.IsDigit(r) {
			if begin < 0 {
				begin = i
			}
		} else if begin >= 0 {
			out = append(out, cleaned[begin:i])
			begin = -1
		}
	}
	if begin >= 0 {
		out = append(out, cleaned[begin:])
	}
	return out, tickets, nums, ctx.Err()
}
