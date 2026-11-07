package store

import (
	"bytes"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestR4OccurrenceIdentityPreservesOldProjections(t *testing.T) {
	for _, labels := range []bool{false, true} {
		t.Run(fmt.Sprint(labels), func(t *testing.T) {
			legacy := r4LegacyHistory(t, []int{0, 0, 0})
			db, err := sql.Open("sqlite", legacy)
			if err != nil {
				t.Fatal(err)
			}
			if !labels {
				if _, err := db.Exec(`UPDATE facts SET keywords='',queries=''`); err != nil {
					t.Fatal(err)
				}
			} else {
				if _, err := db.Exec(`UPDATE facts SET channel=CASE version WHEN 1 THEN '' WHEN 2 THEN 'knowledge' ELSE 'behaviour' END`); err != nil {
					t.Fatal(err)
				}
			}
			if err := db.Close(); err != nil {
				t.Fatal(err)
			}
			old, err := OpenReadOnly(legacy)
			if err != nil {
				t.Fatal(err)
			}
			want, err := old.History(r4FactID)
			if err != nil {
				t.Fatal(err)
			}
			if err := old.Close(); err != nil {
				t.Fatal(err)
			}
			dir := filepath.Join(t.TempDir(), "history")
			file := append([]Fact(nil), want...)
			if !labels {
				for i := range file {
					file[i].WriteID = ""
				}
			} else {
				db, err = sql.Open("sqlite", legacy)
				if err != nil {
					t.Fatal(err)
				}
				if _, err := db.Exec(`ALTER TABLE facts DROP COLUMN channel; PRAGMA user_version=6`); err != nil {
					t.Fatal(err)
				}
				if err := db.Close(); err != nil {
					t.Fatal(err)
				}
			}
			if err := WriteFactFile(FactPath(dir, r4FactID), file); err != nil {
				t.Fatal(err)
			}
			s, err := OpenText(dir, legacy)
			if err != nil {
				t.Fatal(err)
			}
			got, err := s.History(r4FactID)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("occurrence reconciliation manufactured or lost projected writes:\ngot %+v\nwant %+v", got, want)
			}
			if err := s.Close(); err != nil {
				t.Fatal(err)
			}
			// Also exercise Store.Merge into a current history that omitted empty aux.
			if !labels {
				target := filepath.Join(t.TempDir(), "plain.db")
				plain, err := Open(target)
				if err != nil {
					t.Fatal(err)
				}
				legacyRows(t, plain, file...)
				if _, err := plain.Merge(legacy); err != nil {
					t.Fatal(err)
				}
				got, err = plain.History(r4FactID)
				if err != nil || !reflect.DeepEqual(got, want) {
					t.Fatalf("empty auxiliary occurrence identity not persisted by merge: %v; %+v", err, got)
				}
				if err := plain.Close(); err != nil {
					t.Fatal(err)
				}
			}
			s, err = OpenText(dir, legacy)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = s.Close() }()
			got, err = s.History(r4FactID)
			if err != nil || !reflect.DeepEqual(got, want) {
				t.Fatalf("projected occurrences changed on reopen: %v", err)
			}
		})
	}
}

func TestR4AmbiguousMissingLabelCacheRefusesWithoutInventingWrites(t *testing.T) {
	cache := r4LegacyHistory(t, []int{0, 0})
	db, err := sql.Open("sqlite", cache)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`ALTER TABLE facts DROP COLUMN channel; PRAGMA user_version=6`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	// Two differently labelled writes become indistinguishable to this old
	// schema, after an insertion has invalidated positional correspondence.
	dir := filepath.Join(t.TempDir(), "history")
	var raw bytes.Buffer
	for i, item := range []struct{ content, date, channel string }{{"Initial observation.", "01", ""}, {"Left observation.", "02", "knowledge"}, {"Initial observation.", "01", "knowledge"}, {"Initial observation.", "01", "behaviour"}} {
		fmt.Fprintf(&raw, `{"id":%q,"version":%d,"content":%q,"created":"2026-01-%sT00:00:00Z","status":"active","origin":"fixture","author":"writer","expires":"2030-01-01","kind":"environment","scope":"host:fixture","source":"user","evidence":"evidence","review":"candidate","prompt_version":3,"channel":%q,"keywords":["legacy markers"],"queries":["old query"]}`+"\n", r4FactID, i+1, item.content, item.date, item.channel)
	}
	file, err := ParseFacts(raw.Bytes())
	if err != nil {
		t.Fatal(err)
	}
	path := FactPath(dir, r4FactID)
	if err := WriteFactFile(path, file); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	oldCache, err := os.ReadFile(cache)
	if err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, cache)
	if err == nil {
		_ = s.Close()
		t.Fatal("ambiguous old-cache projection accepted an invented correspondence")
	}
	after, e := os.ReadFile(path)
	if e != nil || !bytes.Equal(before, after) {
		t.Fatalf("ambiguity refusal changed fact history: %v", e)
	}
	after, e = os.ReadFile(cache)
	if e != nil || !bytes.Equal(oldCache, after) {
		t.Fatalf("ambiguity refusal changed or retired the old cache: %v", e)
	}
}
