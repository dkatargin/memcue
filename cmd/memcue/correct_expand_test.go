package main

import (
	"bytes"
	"strings"
	"testing"
)

func correctForTest(t *testing.T, args ...string) string {
	t.Helper()
	var out bytes.Buffer
	if err := runCorrect(args, &out); err != nil {
		t.Fatal(err)
	}
	return strings.TrimSpace(out.String())
}

// A lone "--" after the ID separates it from the text, as "--" does before the text of add (#533); a text that starts
// with the word "--" takes a second one.
func TestCorrectSeparator(t *testing.T) {
	env(t)
	id := addFactForTest(t, "-origin", "x 2026-10-22", "Synthetic lantern semaphore protocol")
	for _, c := range []struct {
		args []string
		want string
	}{
		{[]string{id, "Lantern", "protocol", "one"}, "Lantern protocol one"},
		{[]string{id, "--", "Lantern", "protocol", "two"}, "Lantern protocol two"},
		{[]string{"--", id, "Lantern protocol three"}, "Lantern protocol three"},
		{[]string{"--", id, "--", "Lantern protocol four"}, "Lantern protocol four"},
		{[]string{id, "--", "Lantern protocol five"}, "Lantern protocol five"},
		{[]string{id, "--", "--", "Lantern", "protocol", "six"}, "-- Lantern protocol six"},
		{[]string{id, "-- Lantern protocol seven"}, "-- Lantern protocol seven"},
	} {
		correctForTest(t, c.args...)
		if got := storedFact(t, id).Content; got != c.want {
			t.Errorf("correct %q stored %q, want %q", c.args, got, c.want)
		}
	}
	for _, args := range [][]string{{id, "--"}, {"--", id, "--"}, {id}} {
		if err := runCorrect(args, &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "usage") {
			t.Errorf("correct %q: error %v, want the usage", args, err)
		}
	}
}

// A correction writes new text, so the queries of the old one no longer describe the fact: with an API endpoint the
// corrected version gets its own before the command returns (#297).
