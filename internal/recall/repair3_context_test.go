package recall

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestRepair3RankingCancellation(t *testing.T) {
	items := make([]int, 10000)
	for i := range items {
		items[i] = len(items) - i
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	err := sortStableContext(ctx, items, func(i, j int) bool { return items[i] < items[j] })
	if ctx.Err() == nil {
		if err != nil {
			t.Fatal(err)
		}
		return
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("ranking phase ignored cancellation: %v", err)
	}
}

func TestRepair3ContainmentCancellation(t *testing.T) {
	terms := make([]string, 100)
	stems := make([]string, 1000)
	for i := range terms {
		terms[i] = "перезагрузка"
	}
	for i := range stems {
		stems[i] = "совсемдругое"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	_, e := holdsContext(ctx, terms, stems)
	if ctx.Err() == nil {
		if e != nil {
			t.Fatal(e)
		}
		return
	}
	if !errors.Is(e, context.DeadlineExceeded) {
		t.Fatalf("containment phase ignored cancellation: %v", e)
	}
}
