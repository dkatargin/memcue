package text

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"
)

func TestStemsContextInterruptsWork(t *testing.T) {
	input := strings.Repeat("synthetic running перезагрузка PROJ-680 Go 1.27 ", 250000)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err := StemsContext(ctx, input)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("tokenizer ignored in-flight cancellation: %v", err)
	}
	if time.Since(start) > 250*time.Millisecond {
		t.Fatalf("tokenizer did not stop boundedly: %v", time.Since(start))
	}
}

func TestStemsContextMatchesContentOnlyLexer(t *testing.T) {
	for _, s := range []string{"PROJ-680 Go 1.27 перезагрузка PostgreSQL-16", strings.Repeat(" PROJ-681 running #123 !45 @1.2.3.4 ёлка ", 500)} {
		got, err := StemsContext(context.Background(), s)
		if err != nil {
			t.Fatal(err)
		}
		want := Stems(s)
		if strings.Join(got, "\x00") != strings.Join(want, "\x00") {
			t.Fatal("context tokenization changed exact content-only terms/order")
		}
	}
}
