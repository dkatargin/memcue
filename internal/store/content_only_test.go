package store

import (
	"database/sql"
	"path/filepath"
	"testing"

	"github.com/juev/memcue/internal/text"
)

func TestContentOnlyLegacyAuxiliaryNotSearchable(t *testing.T) {
	path := filepath.Join(t.TempDir(), "legacy-schema7.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	// Frozen schema-7 SQL, independent of the current schema and Fact model.
	// An empty derived index makes Open rebuild it from the legacy fact row.
	_, err = db.Exec(`
CREATE TABLE facts (
 id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL,
 keywords TEXT NOT NULL DEFAULT '', origin TEXT NOT NULL DEFAULT '',
 created TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('active', 'retired')),
 author TEXT NOT NULL DEFAULT '', expires TEXT NOT NULL DEFAULT '',
 kind TEXT NOT NULL DEFAULT '', scope TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
 review TEXT NOT NULL DEFAULT '', prompt_version INTEGER NOT NULL DEFAULT 0,
 queries TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL DEFAULT '',
 PRIMARY KEY (id, version)
) WITHOUT ROWID;
CREATE TABLE fact_index (rid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE,
 stems TEXT NOT NULL, numbers INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE fact_fts USING fts5(stems, content='fact_index', content_rowid='rid',
 tokenize='unicode61 remove_diacritics 0');
CREATE TABLE fact_vectors (id TEXT NOT NULL, tag TEXT NOT NULL, dim INTEGER NOT NULL,
 text_hash TEXT NOT NULL, vec BLOB NOT NULL, PRIMARY KEY (id, tag)) WITHOUT ROWID;
CREATE TABLE stamps (name TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
CREATE INDEX facts_created ON facts(created);
CREATE INDEX fact_index_numbers ON fact_index(numbers);
PRAGMA user_version = 7;
INSERT INTO facts (id, version, content, keywords, origin, created, status, author,
 expires, kind, scope, source, evidence, review, prompt_version, queries, channel)
VALUES ('01JCONTENTONLY000000000001', 1, 'Cobalt observatory.', 'saffron',
 'isolated legacy fixture', '2026-01-01T00:00:00Z', 'active', 'legacy-writer',
 '', 'environment', 'global', 'user', 'fixture evidence', 'approved', 3,
 'marigold', 'behaviour');
`)
	closeErr := db.Close()
	if err != nil {
		t.Fatalf("create schema-7 fixture: %v", err)
	}
	if closeErr != nil {
		t.Fatal(closeErr)
	}

	s, err := Open(path)
	if err != nil {
		t.Fatalf("open legacy fixture: %v", err)
	}
	t.Cleanup(func() { _ = s.Close() })
	const id = "01JCONTENTONLY000000000001"
	hits, err := s.Search(text.Terms("cobalt"), 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(hits) != 1 || hits[0].ID != id || hits[0].Content != "Cobalt observatory." {
		t.Fatalf("content query must find the legacy fact unchanged: %+v", hits)
	}
	for _, query := range []struct{ field, word string }{
		{"keywords", "saffron"},
		{"queries", "marigold"},
	} {
		hits, err := s.Search(text.Terms(query.word), 10)
		if err != nil {
			t.Fatalf("%s-only query: %v", query.field, err)
		}
		if len(hits) != 0 {
			t.Errorf("%s-only query %q returned %d fact(s); want none under content-only search", query.field, query.word, len(hits))
		}
	}
}
