package store

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

func TestRepair3MarshalCancellation(t *testing.T) {
	f := Fact{ID: "synthetic", Version: 1, Meta: Meta{Evidence: strings.Repeat("synthetic\\\"\n", 4096)}}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	_, err := marshalFact(ctx, f)
	if ctx.Err() == nil {
		if err != nil {
			t.Fatal(err)
		}
		return
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("native payload encoder ignored cancellation: %v", err)
	}
}
func TestRepair3MarshalEquivalence(t *testing.T) {
	f := Fact{ID: "fixture", Version: 1, Content: "A & B < C ё 😀 \u2028", Created: time.Now().UTC(), Meta: Meta{Evidence: strings.Repeat("\"\\\n😀", 2048)}}
	got, e := marshalFact(context.Background(), f)
	if e != nil {
		t.Fatal(e)
	}
	want, e := json.Marshal(f)
	if e != nil {
		t.Fatal(e)
	}
	if string(got) != string(want) {
		t.Fatal("immutable JSON wire encoding changed")
	}
}

func TestRepair3UnmarshalCancellation(t *testing.T) {
	f := Fact{ID: "synthetic", Version: 1, Meta: Meta{Evidence: strings.Repeat("synthetic\\\"\n", 4096)}}
	b, err := json.Marshal(f)
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	var decoded Fact
	err = unmarshalFact(ctx, b, &decoded)
	if ctx.Err() == nil {
		if err != nil {
			t.Fatal(err)
		}
		return
	}
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("native payload decoder ignored cancellation: %v", err)
	}
}

func TestRepair3JSONDecodeEquivalence(t *testing.T) {
	samples := []string{`null`, `{}`, `{"ID":"x","Version":1,"Evidence":"\ud800\udc00\ud800","Created":"2026-01-01T00:00:00.123456789123Z"}`, `{"id":"first","ID":"last","Version":1,"unknown":{"a":[1,true,null,"x"]}}`, `{"Version":1e0}`, `{"Version":01}`, `{"Content":null,"Created":null}`, `{"ID":"\u0061","Version":9223372036854775808}`}
	for i := 0; i < 8; i++ {
		f := Fact{ID: "fixture", Version: i + 1, Content: strings.Repeat("a😀\"\\\n", 700+i), Created: time.Now().UTC(), Meta: Meta{Evidence: strings.Repeat("ё🦊", 1000)}}
		b, _ := json.Marshal(f)
		samples = append(samples, string(b))
	}
	for _, sample := range samples {
		var a, b Fact
		ea := json.Unmarshal([]byte(sample), &a)
		eb := unmarshalFact(context.Background(), []byte(sample), &b)
		if (ea == nil) != (eb == nil) {
			t.Fatalf("decode validity changed: %v vs %v", ea, eb)
		}
		if ea == nil {
			wa, _ := json.Marshal(a)
			wb, _ := json.Marshal(b)
			if string(wa) != string(wb) {
				t.Fatal("accepted immutable payload meaning changed")
			}
		}
	}
}
