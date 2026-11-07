package store

import (
	"database/sql"
	"path/filepath"
	"reflect"
	"testing"
)

func TestR4EmptyOccurrencesExcludeOtherLegacyAuxiliaryWrites(t *testing.T) {
	legacy := r4LegacyHistory(t, []int{0, 0, 0})
	db, err := sql.Open("sqlite", legacy)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`UPDATE facts SET keywords='',queries='' WHERE version>1`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	source, err := Open(legacy)
	if err != nil {
		t.Fatal(err)
	}
	want, err := source.History(r4FactID)
	if err != nil {
		t.Fatal(err)
	}
	if err := source.Close(); err != nil {
		t.Fatal(err)
	}
	// Current JSONL may retain the identified auxiliary-bearing row alongside
	// old rows whose empty auxiliary lists were omitted. The latter form their
	// own occurrence class; an auxiliary-only write must not consume its rank.
	rows := append([]Fact(nil), want...)
	rows[1].WriteID = ""
	rows[2].WriteID = ""
	target := filepath.Join(t.TempDir(), "current.db")
	s, err := Open(target)
	if err != nil {
		t.Fatal(err)
	}
	legacyRows(t, s, rows...)
	if _, err := s.Merge(legacy); err != nil {
		t.Fatal(err)
	}
	got, err := s.History(r4FactID)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("auxiliary-bearing write shifted empty-auxiliary occurrences: got %d versions, want %d; %+v", len(got), len(want), got)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = Open(target)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	if _, err := s.Merge(legacy); err != nil {
		t.Fatal(err)
	}
	again, err := s.History(r4FactID)
	if err != nil || !reflect.DeepEqual(again, want) {
		t.Fatalf("repeated mixed-identity merge changed history: %v", err)
	}
}
