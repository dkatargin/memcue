package store

import (
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestOldCacheRepeatedProjectionDoesNotInventVersion(t *testing.T) {
	root := t.TempDir()
	cache := filepath.Join(root, "cache.db")
	dir := filepath.Join(root, "history")
	s, err := Open(cache)
	if err != nil {
		t.Fatal(err)
	}
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	first := Fact{ID: id, Version: 1, Content: "Same content in both recorded versions.", Created: time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC), Status: Active, Meta: Meta{Source: "user", Channel: "knowledge"}}
	second := first
	second.Version = 2
	second.Channel = "behaviour"
	want := []Fact{first, second}
	legacyRows(t, s, want...)
	// The old cache could not retain either channel and sees two equal rows.
	if _, err := s.db.Exec(`ALTER TABLE facts DROP COLUMN channel; PRAGMA user_version=6`); err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	if err := WriteFactFile(FactPath(dir, id), want); err != nil {
		t.Fatal(err)
	}
	s, err = OpenText(dir, cache)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	got, err := s.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("old cache projection manufactured versions: got %d want %d; %+v", len(got), len(want), got)
	}
}
