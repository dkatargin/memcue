package store

import (
	"bytes"
	"database/sql"
	"path/filepath"
	"testing"
)

func TestMergedLegacyIdentityPersistsBeforeRenumbering(t *testing.T) {
	legacy := contentLegacyBase(t)
	// Construct a current copy of the same content-only historical writes,
	// as an import of old JSONL with omitted empty auxiliary values would do.
	old, err := sql.Open("sqlite", legacy)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := old.Exec(`UPDATE facts SET keywords='',queries=''`); err != nil {
		t.Fatal(err)
	}
	if err := old.Close(); err != nil {
		t.Fatal(err)
	}
	db, err := Open(legacy)
	if err != nil {
		t.Fatal(err)
	}
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	rows, err := db.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	target := filepath.Join(t.TempDir(), "current.db")
	s, err := Open(target)
	if err != nil {
		t.Fatal(err)
	}
	plain := append([]Fact(nil), rows...)
	for i := range plain {
		plain[i].WriteID = ""
	}
	legacyRows(t, s, plain...)
	if _, err := s.Merge(legacy); err != nil {
		t.Fatal(err)
	}
	got, err := s.History(id)
	if err != nil {
		t.Fatal(err)
	}
	wantBytes, err := EncodeFacts(rows)
	if err != nil {
		t.Fatal(err)
	}
	gotBytes, err := EncodeFacts(got)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(wantBytes, gotBytes) {
		t.Fatal("merge did not persist the canonical write identities before future renumbering")
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
	again, err := s.History(id)
	if err != nil {
		t.Fatal(err)
	}
	b, err := EncodeFacts(again)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(b, wantBytes) {
		t.Fatal("identity changed across reopen/repeated merge")
	}
}
