package text

import (
	"context"
	"errors"
	"math/rand"
	"strings"
	"testing"
	"time"
)

func TestRepair3LexicalPhaseCancellation(t *testing.T) {
	// Finite 64KiB fixture, not a capacity/DoS experiment: one ticket match.
	input := "PROJ" + strings.Repeat("A", 65536) + "-123"
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	_, _, _, err := wordPartsContext(ctx, input)
	if ctx.Err() == nil {
		if err != nil {
			t.Fatal(err)
		}
		return // valid completion before the timer fires
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("lexical phase ignored in-flight cancellation: %v", err)
	}
}

func TestRepair3LexerEquivalence(t *testing.T) {
	samples := []string{"v1.27 1.2.3x @1.1.1.1 PROJ-123 #123abc", "Go PostgreSQL-16 перезагрузка ёлка 1-2 /v1.2 :1.2", "\r1.2\f2.3 !45 PROJ-A 12", "a1.2 (v1.2) nm1.2 1.2.3x 1.2x"}
	for _, s := range samples {
		a, b, c := wordParts(s)
		x, y, z, e := wordPartsContext(context.Background(), s)
		if e != nil {
			t.Fatal(e)
		}
		if strings.Join(a, "|") != strings.Join(x, "|") || strings.Join(b, "|") != strings.Join(y, "|") || strings.Join(c, "|") != strings.Join(z, "|") {
			t.Fatalf("lexer mismatch %q: old=%q %q %q new=%q %q %q", s, a, b, c, x, y, z)
		}
	}
}

func TestRepair3StemPhaseCancellation(t *testing.T) {
	word := strings.Repeat("ab", 32768) + "ingly"
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	_, _, err := stemContext(ctx, word)
	if ctx.Err() == nil {
		if err != nil {
			t.Fatal(err)
		}
		return // completed before cancellation; race run establishes the interrupt opportunity
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("Snowball phase ignored cancellation: %v", err)
	}
}

func TestRepair3DifferentialLexerAndStem(t *testing.T) {
	r := rand.New(rand.NewSource(680681))
	alphabet := []rune("abZPROJ019-.:/@#!_ \t\r\f\n()ёя中")
	for i := 0; i < 1500; i++ {
		var b strings.Builder
		for j := 0; j < 300; j++ {
			b.WriteRune(alphabet[r.Intn(len(alphabet))])
		}
		s := b.String()
		a, x, y := wordParts(s)
		aa, xx, yy, e := wordPartsContext(context.Background(), s)
		if e != nil {
			t.Fatal(e)
		}
		if strings.Join(a, "|") != strings.Join(aa, "|") || strings.Join(x, "|") != strings.Join(xx, "|") || strings.Join(y, "|") != strings.Join(yy, "|") {
			t.Fatalf("differential lexer %q: old=%q %q %q new=%q %q %q", s, a, x, y, aa, xx, yy)
		}
	}
	for _, suffix := range []string{"ing", "ingly", "ational", "ement", "s", "y", "ость", "иями", "ющий", "а"} {
		for _, prefix := range []string{strings.Repeat("ab", 512), strings.Repeat("перезагруз", 64)} {
			s := prefix + suffix
			want, ok := stem(s)
			got, gok, e := stemContext(context.Background(), s)
			if e != nil || ok != gok || want != got {
				t.Fatalf("long-word stem equivalence: ok=%t/%t error=%v", ok, gok, e)
			}
		}
	}
}
