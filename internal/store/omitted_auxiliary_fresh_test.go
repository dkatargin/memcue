package store

import (
	"database/sql"
	"path/filepath"
	"testing"
)

func TestLegacyOmittedAuxiliaryFieldsDoNotDuplicateCacheRows(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	cache := contentLegacyBase(t)
	db, err := sql.Open("sqlite", cache)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`UPDATE facts SET keywords='',queries=''`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	old, err := OpenReadOnly(cache)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := old.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := old.Close(); err != nil {
		t.Fatal(err)
	}
	// Published JSONL omitted empty auxiliary lists; there is no auxiliary key
	// to trigger projection, even though SQLite still has the empty columns.
	for i := range rows {
		rows[i].WriteID = ""
	}
	dir := filepath.Join(t.TempDir(), "history")
	if err := WriteFactFile(FactPath(dir, id), rows); err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, cache)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	got, err := s.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != len(rows) {
		t.Fatalf("omitted legacy auxiliary fields manufactured cache writes: got %d want %d", len(got), len(rows))
	}
	for i, f := range got {
		if f.Content != rows[i].Content || f.Version != rows[i].Version || f.Meta != rows[i].Meta || f.Author != rows[i].Author || !f.Created.Equal(rows[i].Created) {
			t.Fatalf("recorded write changed: %+v", f)
		}
	}
}
