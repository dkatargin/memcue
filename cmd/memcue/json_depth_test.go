package main

import (
	"context"
	"encoding/json"
	"strings"
	"testing"
)

func TestNativeUnknownJSONDepthMatchesStandardLimit(t *testing.T) {
	for _, n := range []int{9998, 9999, 10000, 10001} {
		input := `{"unknown":` + strings.Repeat("[", n) + strings.Repeat("]", n) + `,"cwd":"synthetic"}`
		var baseline, got sessionStartInput
		expectedErr := json.Unmarshal([]byte(input), &baseline)
		inv := &invocation{ctx: context.Background(), stop: func() {}}
		e := inv.decodeInput(strings.NewReader(input), &got)
		if (e == nil) != (expectedErr == nil) {
			t.Fatalf("native JSON depth %d plus root must match standard 10000-container limit: standard error=%t native error=%t", n, expectedErr != nil, e != nil)
		}
		if e == nil && got != baseline {
			t.Fatal("valid deep unknown-field equivalence changed")
		}
	}
}
