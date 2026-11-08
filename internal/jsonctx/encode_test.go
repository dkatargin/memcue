package jsonctx

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"
)

func TestEncoderContextCancellation(t *testing.T) {
	v := struct {
		Content string `json:"content"`
	}{strings.Repeat("synthetic\\\"\n", 4096)}
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Microsecond)
	defer cancel()
	_, e := Marshal(ctx, v)
	if ctx.Err() == nil {
		if e != nil {
			t.Fatal(e)
		}
		return
	}
	if !errors.Is(e, context.DeadlineExceeded) {
		t.Fatalf("output serialization ignored cancellation: %v", e)
	}
}

func TestEncoderWireEquivalence(t *testing.T) {
	for _, v := range []any{map[string]any{"z": "a😀\\\n<", "a": []int{1, 2}}, struct {
		A string   `json:"a,omitempty"`
		B *bool    `json:"b,omitempty"`
		C []string `json:"c"`
	}{C: []string{}}, []byte("synthetic"), struct{ Created time.Time }{time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)}} {
		a, e := json.Marshal(v)
		if e != nil {
			t.Fatal(e)
		}
		b, e := Marshal(context.Background(), v)
		if e != nil || string(a) != string(b) {
			t.Fatalf("wire meaning/shape changed: %v", e)
		}
	}
}
