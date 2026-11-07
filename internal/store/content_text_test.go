package store

import (
	"bytes"
	"database/sql"
	"github.com/juev/memcue/internal/text"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
)

func TestContentOnlyLegacyTextUpgrade(t *testing.T) {
	for _, cached := range []bool{false, true} {
		name := "without-cache"
		if cached {
			name = "pending-cache"
		}
		t.Run(name, func(t *testing.T) {
			dir := filepath.Join(t.TempDir(), "history")
			cache := filepath.Join(t.TempDir(), "cache.db")
			if cached {
				cache = contentLegacyBase(t)
			}
			path := FactPath(dir, "01AAAAAAAAAAAAAAAAAAAAAAA1")
			if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			const line = `{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":1,"created":"2026-01-01T00:00:00.123Z","status":"active","author":"author","content":"Первоначальный PROJ-1234","keywords":["saffron"],"origin":"origin","kind":"rule","scope":"global","source":"user","evidence":"evidence","review":"candidate","prompt_version":3,"queries":["marigold"],"channel":"behaviour"}` + "\n"
			if err := os.WriteFile(path, []byte(line), 0600); err != nil {
				t.Fatal(err)
			}
			var expected []Fact
			if cached {
				old, err := OpenReadOnly(cache)
				if err != nil {
					t.Fatal(err)
				}
				expected, err = old.Rows()
				if err != nil {
					t.Fatal(err)
				}
				if err := old.Close(); err != nil {
					t.Fatal(err)
				}
			} else {
				var err error
				expected, err = ParseFacts([]byte(line))
				if err != nil {
					t.Fatal(err)
				}
			}
			for attempt := 0; attempt < 2; attempt++ {
				s, err := OpenText(dir, cache)
				if err != nil {
					t.Fatal(err)
				}
				actual, err := s.Rows()
				if err != nil {
					t.Fatal(err)
				}
				if !reflect.DeepEqual(actual, expected) {
					t.Errorf("text upgrade changed complete metadata/version chains: got %+v want %+v", actual, expected)
				}
				for _, word := range []string{"saffron", "marigold"} {
					hits, err := s.Search(text.Terms(word), 10)
					if err != nil {
						t.Fatal(err)
					}
					if len(hits) != 0 {
						t.Errorf("text upgrade retained auxiliary term %q", word)
					}
				}
				history, err := s.History("01AAAAAAAAAAAAAAAAAAAAAAA1")
				if err != nil {
					t.Fatal(err)
				}
				want := 1
				if cached {
					want = 2
				}
				if len(history) != want {
					t.Errorf("cache-only version lost: got %d versions want %d", len(history), want)
				}
				f := history[0]
				if f.Content != "Первоначальный PROJ-1234" || f.Origin != "origin" || f.Author != "author" || f.Source != "user" || f.Evidence != "evidence" || f.Channel != "behaviour" || f.PromptVersion != 3 || f.Review != "candidate" || f.Created.Format("2006-01-02T15:04:05.000Z") != "2026-01-01T00:00:00.123Z" {
					t.Errorf("changed legacy data: %+v", f)
				}
				if err := s.Close(); err != nil {
					t.Fatal(err)
				}
				backup, err := legacyTextBackupPath(dir, cache)
				if err != nil {
					t.Fatal(err)
				}
				files, err := filepath.Glob(filepath.Join(backup, "*.jsonl"))
				if err != nil {
					t.Fatal(err)
				}
				if len(files) != 1 {
					t.Errorf("original JSONL backup count %d want 1", len(files))
				} else {
					saved, err := os.ReadFile(files[0])
					if err != nil {
						t.Fatal(err)
					}
					if !bytes.Equal(saved, []byte(line)) {
						t.Error("original JSONL backup bytes changed")
					}
				}
				data, err := os.ReadFile(path)
				if err != nil {
					t.Fatal(err)
				}
				if strings.Contains(string(data), `"keywords"`) || strings.Contains(string(data), `"queries"`) {
					t.Error("current text history retains auxiliary keys")
				}
			}
		})
	}
}

func TestContentOnlyRefusesUnreadableCache(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "history")
	cache := filepath.Join(root, "cache.db")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	const damaged = "not a SQLite database; pending versions cannot be proven absent"
	if err := os.WriteFile(cache, []byte(damaged), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, cache)
	if err == nil {
		_ = s.Close()
		t.Error("unreadable cache was silently replaced instead of refusing potential pending-version loss")
	}
	data, err := os.ReadFile(cache)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != damaged {
		t.Error("refusal changed unreadable cache")
	}
}

func TestContentOnlyConcurrentLegacyTextOpens(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "history")
	cache := contentLegacyBase(t)
	var wg sync.WaitGroup
	errs := make(chan error, 2)
	for range 2 {
		wg.Go(func() {
			s, err := OpenText(dir, cache)
			if err == nil {
				err = s.Close()
			}
			errs <- err
		})
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		if err != nil {
			t.Fatal(err)
		}
	}
	s, err := OpenText(dir, cache)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	rows, err := s.Rows()
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 6 {
		t.Errorf("concurrent migration lost/duplicated rows: %d", len(rows))
	}
	textMatches(t, s)
	files, err := filepath.Glob(filepath.Join(dir, "*", "*.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range files {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(data), `"keywords"`) || strings.Contains(string(data), `"queries"`) {
			t.Error("auxiliary keys reintroduced")
		}
	}
}

func TestContentOnlyTextBackupStaysOutsideHistory(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "history")
	cache := filepath.Join(dir, "cache.db")
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	path := FactPath(dir, id)
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	const legacy = `{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":1,"created":"2026-01-01T00:00:00Z","status":"active","content":"Cobalt observatory.","source":"user","keywords":["saffron"],"queries":["marigold"]}` + "\n"
	if err := os.WriteFile(path, []byte(legacy), 0600); err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, cache)
	if err != nil {
		t.Fatalf("legacy rewrite failed with cache inside history: %v", err)
	}
	defer func() { _ = s.Close() }()
	textMatches(t, s)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(data), `"keywords"`) || strings.Contains(string(data), `"queries"`) {
		t.Error("auxiliary keys remain")
	}
	if _, err := os.Stat(cache + ".schema7-text-backup"); !os.IsNotExist(err) {
		t.Error("legacy backup was placed inside current history")
	}
}

func TestContentOnlyRefusesNewerCache(t *testing.T) {
	cache := contentLegacyBase(t)
	db, err := sql.Open("sqlite", cache)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`PRAGMA user_version=99`); err != nil {
		t.Fatal(err)
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(cache)
	if err != nil {
		t.Fatal(err)
	}
	if s, err := OpenText(filepath.Join(t.TempDir(), "history"), cache); err == nil {
		_ = s.Close()
		t.Error("newer cache silently replaced")
	}
	after, err := os.ReadFile(cache)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(before, after) {
		t.Error("newer cache refusal changed its bytes")
	}
}
