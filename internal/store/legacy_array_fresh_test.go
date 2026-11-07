package store

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestLegacyArrayAuxiliaryIdentityMatchesSQLite(t *testing.T) {
	cache := contentLegacyBase(t)
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	old, err := OpenReadOnly(cache)
	if err != nil {
		t.Fatal(err)
	}
	want, err := old.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if err := old.Close(); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(t.TempDir(), "history")
	path := FactPath(dir, id)
	raw := []byte(`{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":1,"created":"2026-01-01T00:00:00.123Z","status":"active","author":"author","content":"Первоначальный PROJ-1234","keywords":["saffron"],"origin":"origin","kind":"rule","scope":"global","source":"user","evidence":"evidence","review":"candidate","prompt_version":3,"queries":["marigold"],"channel":"behaviour"}` + "\n")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, cache)
	if err != nil {
		t.Fatalf("published legacy array history was refused: %v", err)
	}
	defer func() { _ = s.Close() }()
	got, err := s.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("same legacy write acquired two identities:\nwant %+v\ngot %+v", want, got)
	}
}
