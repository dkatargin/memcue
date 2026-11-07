package store

import (
	"bytes"
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

// A coordinated upgrade can encounter several different old caches at the same
// path. Every retired cache is rollback evidence, including its auxiliary text.
func TestRepeatedLegacyCacheRetirementPreservesBytes(t *testing.T) {
	root := t.TempDir()
	history, cache := filepath.Join(root, "history"), filepath.Join(root, "cache.db")
	// Build distinct, closed schema-7 databases before exercising retirement.
	// The literal old schema deliberately does not depend on the current schema.
	fixtures := make([][]byte, 3)
	for i := range fixtures {
		path := filepath.Join(root, fmt.Sprintf("legacy-%d.db", i))
		db, err := sql.Open("sqlite", path)
		if err != nil {
			t.Fatal(err)
		}
		_, err = db.Exec(`
CREATE TABLE facts (
 id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
 keywords TEXT NOT NULL DEFAULT '', queries TEXT NOT NULL DEFAULT '',
 origin TEXT NOT NULL DEFAULT '', created TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('active','retired')),
 author TEXT NOT NULL DEFAULT '', expires TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
 review TEXT NOT NULL DEFAULT '', prompt_version INTEGER NOT NULL DEFAULT 0,
 channel TEXT NOT NULL DEFAULT '', PRIMARY KEY(id,version)
) WITHOUT ROWID;
CREATE TABLE fact_index (rid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, stems TEXT NOT NULL, numbers INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE fact_fts USING fts5(stems, content='fact_index', content_rowid='rid');
CREATE TABLE stamps (name TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
PRAGMA user_version = 7;
`)
		if err != nil {
			_ = db.Close()
			t.Fatal(err)
		}
		_, err = db.Exec(`INSERT INTO facts(id,version,content,keywords,queries,created,status,source)
VALUES (?,1,?,?,?,'2026-11-01T12:00:00Z','active','user')`,
			fmt.Sprintf("01JCACHE00000000000000000%d", i),
			fmt.Sprintf("Recorded cache payload %d.", i),
			fmt.Sprintf("legacykeyword%d", i), fmt.Sprintf("legacy query %d", i))
		if err != nil {
			_ = db.Close()
			t.Fatal(err)
		}
		if err := db.Close(); err != nil {
			t.Fatal(err)
		}
		fixtures[i], err = os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if i > 0 && bytes.Equal(fixtures[0], fixtures[i]) {
			t.Fatal("fixture caches must differ")
		}
	}
	saved := map[string][]byte{}
	for i, original := range fixtures {
		if err := os.WriteFile(cache, original, 0600); err != nil {
			t.Fatal(err)
		}
		s, err := OpenText(history, cache)
		if err != nil {
			t.Fatalf("retire legacy cache %d: %v", i, err)
		}
		if err := s.Close(); err != nil {
			t.Fatal(err)
		}
		for path, want := range saved {
			got, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("previously preserved cache unavailable after retirement %d: %v", i, err)
			}
			if !bytes.Equal(got, want) {
				t.Fatalf("previously preserved cache bytes changed after retirement %d: %s", i, filepath.Base(path))
			}
		}
		paths, err := filepath.Glob(cache + ".schema*")
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, path := range paths {
			info, err := os.Stat(path)
			if err != nil {
				t.Fatal(err)
			}
			if !info.Mode().IsRegular() {
				continue
			}
			data, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			if bytes.Equal(data, original) {
				found = true
			}
			saved[path] = data
		}
		if !found {
			t.Fatalf("retired cache %d was not preserved byte-for-byte", i)
		}
	}
}
