package store

import (
	"database/sql"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLegacyCacheRescueUnionsDivergentWrites(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	cache := contentLegacyBase(t)
	legacy, err := OpenReadOnly(cache)
	if err != nil {
		t.Fatal(err)
	}
	pending, err := legacy.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := legacy.Close(); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(t.TempDir(), "history")
	file := append([]Fact(nil), pending...)
	file[1].Content = "File branch: PROJ-1234 on port 7777."
	file[1].WriteID = ""
	retired := file[1]
	retired.Version = 3
	retired.Status = Retired
	file = append(file, retired)
	if err := WriteFactFile(FactPath(dir, id), file); err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, cache)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := s.History(id)
	if err != nil {
		t.Fatal(err)
	}
	found := false
	for _, f := range rows {
		if f.Content == pending[1].Content && f.Status == Active {
			found = true
		}
	}
	if !found {
		t.Fatal("pending cache write at version 2 was lost below file tail 3")
	}
	if len(rows) != 4 {
		t.Fatalf("history union has %d versions, want 4", len(rows))
	}
	if rows[len(rows)-1].Content != pending[1].Content || rows[len(rows)-1].Status != Active {
		t.Fatal("unseen cache correction did not survive file retirement")
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	s, err = OpenText(dir, cache)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	again, err := s.History(id)
	if err != nil || !reflect.DeepEqual(rows, again) {
		t.Fatalf("reopening changed rescued history: %v", err)
	}
	disk, err := ReadFactFile(FactPath(dir, id))
	if err != nil || !reflect.DeepEqual(rows, disk) {
		t.Fatalf("rescued file and cache disagree: %v", err)
	}
}

func TestOlderCacheMissingChannelDoesNotInventWrites(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	cache := contentLegacyBase(t)
	db, err := sql.Open("sqlite", cache)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`DELETE FROM facts WHERE id<>? OR version<>1; ALTER TABLE facts DROP COLUMN channel; PRAGMA user_version=6`, id); err != nil {
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
	// Text already recorded the label; an older reader could only cache its
	// projection without channel. Opening that cache must not add a third write.
	rows[0].Channel = "knowledge"
	labelled := rows[0]
	labelled.Version = 2
	labelled.Channel = "behaviour"
	labelled.WriteID = ""
	rows = append(rows, labelled)
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
	if !reflect.DeepEqual(rows, got) {
		t.Fatalf("older cache manufactured historical writes:\nwant %+v\ngot %+v", rows, got)
	}
}
