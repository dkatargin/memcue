package store

import (
	"bytes"
	"crypto/sha256"
	"database/sql"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/juev/memcue/internal/text"
)

// SQL here deliberately describes the published schema, not the current schema constant.
func contentLegacyBase(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "legacy.db")
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = db.Close() }()
	_, err = db.Exec(`CREATE TABLE facts (
 id TEXT NOT NULL, version INTEGER NOT NULL, content TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '',
 origin TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('active','retired')),
 author TEXT NOT NULL DEFAULT '', expires TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT '',
 scope TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '', evidence TEXT NOT NULL DEFAULT '',
 review TEXT NOT NULL DEFAULT '', prompt_version INTEGER NOT NULL DEFAULT 0, queries TEXT NOT NULL DEFAULT '',
 channel TEXT NOT NULL DEFAULT '', PRIMARY KEY(id,version)) WITHOUT ROWID;
 CREATE TABLE fact_index (rid INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, stems TEXT NOT NULL, numbers INTEGER NOT NULL DEFAULT 0);
 CREATE VIRTUAL TABLE fact_fts USING fts5(stems,content='fact_index',content_rowid='rid',tokenize='unicode61 remove_diacritics 0');
 CREATE TABLE fact_vectors (id TEXT NOT NULL,tag TEXT NOT NULL,dim INTEGER NOT NULL,text_hash TEXT NOT NULL,vec BLOB NOT NULL,PRIMARY KEY(id,tag)) WITHOUT ROWID;
 CREATE TABLE stamps(name TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;
 PRAGMA user_version=7;
 INSERT INTO facts VALUES ('01AAAAAAAAAAAAAAAAAAAAAAA1',1,'Первоначальный PROJ-1234','saffron','origin','2026-01-01T00:00:00.123Z','active','author','','rule','global','user','evidence','candidate',3,'marigold','behaviour');
 INSERT INTO facts SELECT id,2,'Исправленный PROJ-1234',keywords,origin,'2026-02-01T00:00:00.456Z',status,author,expires,kind,scope,source,evidence,review,prompt_version,queries,channel FROM facts WHERE id='01AAAAAAAAAAAAAAAAAAAAAAA1';
 INSERT INTO facts SELECT '01AAAAAAAAAAAAAAAAAAAAAAA2',version,content,keywords,origin,created,'retired',author,expires,kind,scope,source,evidence,review,prompt_version,queries,channel FROM facts WHERE id='01AAAAAAAAAAAAAAAAAAAAAAA1';
 INSERT INTO facts SELECT '01AAAAAAAAAAAAAAAAAAAAAAA3',version,content,keywords,origin,created,status,author,'2020-01-01',kind,scope,source,evidence,review,prompt_version,queries,channel FROM facts WHERE id='01AAAAAAAAAAAAAAAAAAAAAAA1';
 INSERT INTO fact_index(id,stems,numbers) VALUES ('01AAAAAAAAAAAAAAAAAAAAAAA1','исправлен tkproj1234 saffron marigold',2),('01AAAAAAAAAAAAAAAAAAAAAAA3','исправлен tkproj1234 saffron marigold',2);
 INSERT INTO fact_fts(rowid,stems) SELECT rid,stems FROM fact_index;
 INSERT INTO stamps VALUES ('live-index','facts=6 index=2 fts=2');`)
	if err != nil {
		t.Fatal(err)
	}
	return path
}

func TestContentOnlySchemaUpgrade(t *testing.T) {
	path := contentLegacyBase(t)
	// Read expected data independently of the new Fact API and auxiliary columns.
	read := func(db *sql.DB) []string {
		t.Helper()
		rows, err := db.Query(`SELECT id,version,content,origin,created,status,author,expires,kind,scope,source,evidence,review,prompt_version,channel FROM facts ORDER BY id,version`)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = rows.Close() }()
		var out []string
		for rows.Next() {
			var values [15]string
			args := make([]any, len(values))
			for i := range values {
				args[i] = &values[i]
			}
			if err := rows.Scan(args...); err != nil {
				t.Fatal(err)
			}
			out = append(out, strings.Join(values[:], "\x00"))
		}
		if err := rows.Err(); err != nil {
			t.Fatal(err)
		}
		return out
	}
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	want := read(db)
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	for attempt := 0; attempt < 2; attempt++ {
		s, err := Open(path)
		if err != nil {
			t.Fatal(err)
		}
		if got := read(s.db); !reflect.DeepEqual(got, want) {
			t.Errorf("metadata/history changed: got %q want %q", got, want)
		}
		cols, err := factColumns(s.db)
		if err != nil {
			t.Fatal(err)
		}
		if cols["keywords"] || cols["queries"] {
			t.Error("current facts table still contains auxiliary fields")
		}
		for _, q := range []string{"saffron", "marigold"} {
			hits, err := s.Search(text.Terms(q), 10)
			if err != nil {
				t.Fatal(err)
			}
			if len(hits) != 0 {
				t.Errorf("stamped legacy index retained %q: %d hits", q, len(hits))
			}
		}
		for _, q := range []string{"Исправленный", "PROJ-1234"} {
			hits, err := s.SearchFiltered(text.Terms(q), 10, Filter{Today: time.Now().Format(time.DateOnly)})
			if err != nil {
				t.Fatal(err)
			}
			if len(hits) != 1 || hits[0].ID != "01AAAAAAAAAAAAAAAAAAAAAAA1" {
				t.Errorf("content query %q: %+v", q, hits)
			}
		}
		if err := s.Close(); err != nil {
			t.Fatal(err)
		}
	}
}

func TestContentOnlyMigrationRollbackAndRetry(t *testing.T) {
	path := contentLegacyBase(t)
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`CREATE TRIGGER legacy_dependency AFTER INSERT ON facts BEGIN SELECT new.keywords; END;`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	if s, err := Open(path); err == nil {
		_ = s.Close()
		t.Fatal("migration with an unsupported legacy dependency succeeded")
	}
	db, err = sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	var v int
	if err := db.QueryRow(`PRAGMA user_version`).Scan(&v); err != nil {
		t.Fatal(err)
	}
	have, err := factColumns(db)
	if err != nil {
		t.Fatal(err)
	}
	if v != 7 || !have["keywords"] || !have["queries"] {
		t.Errorf("failed migration left partial upgrade: schema=%d columns=%v", v, have)
	}
	var n int
	if err := db.QueryRow(`SELECT count(*) FROM facts WHERE keywords='saffron' AND queries='marigold'`).Scan(&n); err != nil || n != 6 {
		t.Errorf("failed migration changed legacy rows: n=%d err=%v", n, err)
	}
	if _, err := db.Exec(`DROP TRIGGER legacy_dependency`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	s, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	have, err = factColumns(s.db)
	if err != nil {
		t.Fatal(err)
	}
	if have["keywords"] || have["queries"] {
		t.Error("retry did not finish migration")
	}
}

func TestContentOnlyLegacyMergeDoesNotRestoreAuxiliary(t *testing.T) {
	path := contentLegacyBase(t)
	other := filepath.Join(t.TempDir(), "copy.db")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(other, data, 0600); err != nil {
		t.Fatal(err)
	}
	a, err := Open(path)
	if err != nil {
		t.Fatal(err)
	}
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	before, err := a.History(id)
	if err != nil {
		t.Fatal(err)
	}
	b, err := Open(other)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := a.Retire(id); err != nil {
		t.Fatal(err)
	}
	if _, err := b.Relabel(id, 2, "rule", "host:isolated", ""); err != nil {
		t.Fatal(err)
	}
	if err := b.Close(); err != nil {
		t.Fatal(err)
	}
	if _, err := a.Merge(other); err != nil {
		t.Fatal(err)
	}
	current, err := a.Get(id)
	if err != nil {
		t.Fatal(err)
	}
	if current.Status != Retired {
		t.Error("label-only divergence resurrected a retirement")
	}
	history, err := a.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if len(history) < len(before) || !reflect.DeepEqual(history[:len(before)], before) {
		t.Error("merge rewrote original versions")
	}
	if _, err := a.Merge(other); err != nil {
		t.Fatal(err)
	}
	again, err := a.History(id)
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(history, again) {
		t.Error("repeated merge changed history")
	}
	if err := a.Close(); err != nil {
		t.Fatal(err)
	}
	a, err = Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = a.Close() }()
	for _, q := range []string{"saffron", "marigold"} {
		hits, err := a.Search(text.Terms(q), 10)
		if err != nil {
			t.Fatal(err)
		}
		if len(hits) != 0 {
			t.Errorf("merge restored auxiliary term %q", q)
		}
	}
	have, err := factColumns(a.db)
	if err != nil {
		t.Fatal(err)
	}
	if have["keywords"] || have["queries"] {
		t.Error("merge restored auxiliary columns")
	}
}

func TestContentOnlyReadOnlyLegacyInspection(t *testing.T) {
	path := contentLegacyBase(t)
	before, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	r, err := OpenReadOnly(path)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := r.Rows()
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 6 {
		t.Errorf("historical rows: %d", len(rows))
	}
	var out bytes.Buffer
	if err := r.Dump(&out); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(out.String(), "Первоначальный PROJ-1234") || strings.Contains(out.String(), "saffron") || strings.Contains(out.String(), "marigold") {
		t.Errorf("historical inspection: %s", out.String())
	}
	if err := r.Close(); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if sha256.Sum256(before) != sha256.Sum256(after) {
		t.Error("read-only inspection changed the legacy base")
	}
}
