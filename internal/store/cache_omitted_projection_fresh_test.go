package store

import (
	"database/sql"
	"path/filepath"
	"testing"
)

func TestMissingOldCacheLabelsAndOmittedAuxiliaryDoNotInventWrites(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	cache := contentLegacyBase(t)
	db, err := sql.Open("sqlite", cache)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`UPDATE facts SET keywords='',queries=''; ALTER TABLE facts DROP COLUMN channel; PRAGMA user_version=6`); err != nil {
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
	for i := range rows {
		rows[i].WriteID = ""
		rows[i].Channel = "behaviour"
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
	if len(got) != 2 {
		t.Fatalf("missing cache fields manufactured writes with omitted auxiliary fields: got %d want 2", len(got))
	}
	for i, f := range got {
		if f.Content != rows[i].Content || f.Meta != rows[i].Meta || f.Version != rows[i].Version {
			t.Fatalf("old cache lost recorded labels: %+v", f)
		}
	}
}
