package main

import (
	"bytes"
	"testing"
	"time"
)

// Restored content-only freshness coverage: metadata labels do not request a
// second content review, but a subsequent text correction does.
func TestContentOnlyLabelFreshnessVersusCorrection(t *testing.T) {
	env(t)
	id := addFactForTest(t, "Unchanged observatory observation.")
	s, err := openBase()
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]int{id: 1}
	if _, err := s.Relabel(id, 1, "environment", "host:fixture", "2030-01-01"); err != nil {
		t.Fatal(err)
	}
	active, err := s.Active()
	if err != nil {
		t.Fatal(err)
	}
	fresh, err := freshFacts(s, active, time.Time{}, seen)
	if err != nil {
		t.Fatal(err)
	}
	if len(fresh) != 0 {
		t.Fatalf("metadata label made content fresh: %+v", fresh)
	}
	if _, err := s.Correct(id, "Actually corrected observatory observation."); err != nil {
		t.Fatal(err)
	}
	active, err = s.Active()
	if err != nil {
		t.Fatal(err)
	}
	fresh, err = freshFacts(s, active, time.Time{}, seen)
	if err != nil {
		t.Fatal(err)
	}
	if len(fresh) != 1 || fresh[0].ID != id || fresh[0].Version != 3 {
		t.Fatalf("actual correction was not fresh: %+v", fresh)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if err := runDream([]string{"-prepare", "-all"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
}
