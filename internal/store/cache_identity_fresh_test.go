package store

import (
	"database/sql"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// Supplemental proof of the already repaired identity/rescue contract, without
// a new production change or a claimed RED.
func TestAuxiliaryOnlyCacheDivergenceRetainsBothWrites(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	cache := contentLegacyBase(t)
	db, err := sql.Open("sqlite", cache)
	if err != nil {
		t.Fatal(err)
	}
	_, err = db.Exec(`UPDATE facts SET content='Первоначальный PROJ-1234',created='2026-01-01T00:00:00.123Z',keywords='cache-only' WHERE id=? AND version=2`, id)
	if err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	r, err := OpenReadOnly(cache)
	if err != nil {
		t.Fatal(err)
	}
	pending, err := r.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := r.Close(); err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	dir := filepath.Join(root, "history")
	path := FactPath(dir, id)
	const fields = `"created":"2026-01-01T00:00:00.123Z","status":"active","author":"author","content":"Первоначальный PROJ-1234","origin":"origin","kind":"rule","scope":"global","source":"user","evidence":"evidence","review":"candidate","prompt_version":3,"queries":["marigold"],"channel":"behaviour"`
	raw := []byte(`{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":1,"keywords":["saffron"],` + fields + "}\n" + `{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":2,"keywords":["file-only"],` + fields + "}\n")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
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
	if len(rows) != 3 {
		t.Fatalf("auxiliary-only pending write lost: %d versions", len(rows))
	}
	identities := map[string]bool{}
	for i, f := range rows {
		identities[f.WriteID] = true
		f.Version = pending[0].Version
		f.WriteID = pending[0].WriteID
		if !reflect.DeepEqual(f, pending[0]) {
			t.Fatalf("metadata or content changed at %d: %+v", i, f)
		}
	}
	if !identities[pending[1].WriteID] || len(identities) != 3 {
		t.Fatal("distinct original writes were collapsed")
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
		t.Fatalf("rescue not idempotent: %v", err)
	}
}
