package store

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

func TestLegacyBackupPlacementResolvesFilesystemAliases(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	raw := []byte(`{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":1,"created":"2026-01-01T00:00:00Z","status":"active","source":"user","content":"Keep original.","keywords":"obsolete","queries":"old"}` + "\n")
	for _, layout := range []string{"history-alias", "backup-parent-alias", "backup-leaf-alias", "absent-backup-under-aliased-parent"} {
		t.Run(layout, func(t *testing.T) {
			root := t.TempDir()
			real := filepath.Join(root, "real")
			history := filepath.Join(real, "history")
			if err := os.MkdirAll(history, 0700); err != nil {
				t.Fatal(err)
			}
			alias := filepath.Join(root, "alias")
			if err := os.Symlink(real, alias); err != nil {
				t.Fatal(err)
			}
			cache := filepath.Join(root, "cache.db")
			switch layout {
			case "history-alias":
				history = filepath.Join(alias, "history")
				cache = filepath.Join(real, "history", "cache.db")
			case "backup-parent-alias":
				link := filepath.Join(root, "into-history")
				if err := os.Symlink(history, link); err != nil {
					t.Fatal(err)
				}
				cache = filepath.Join(link, "cache.db")
			case "backup-leaf-alias":
				if err := os.Symlink(history, cache+".schema7-text-backup"); err != nil {
					t.Fatal(err)
				}
			case "absent-backup-under-aliased-parent":
				link := filepath.Join(root, "into-history")
				if err := os.Symlink(history, link); err != nil {
					t.Fatal(err)
				}
				cache = filepath.Join(link, "new", "cache.db")
			}
			path := FactPath(history, id)
			if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, raw, 0600); err != nil {
				t.Fatal(err)
			}
			s, err := OpenText(history, cache)
			if err != nil {
				if layout == "history-alias" {
					t.Fatalf("normal history alias refused: %v", err)
				}
				after, e := os.ReadFile(path)
				if e != nil || !bytes.Equal(after, raw) {
					t.Fatalf("unsafe layout mutated history before refusal: %v", e)
				}
				return
			}
			if err := s.Close(); err != nil {
				t.Fatal(err)
			}
			// Inspect actual saved bytes, not a lexical prefix or a backup-name count.
			found := false
			err = filepath.WalkDir(root, func(p string, d os.DirEntry, e error) error {
				if e != nil {
					return e
				}
				if !d.Type().IsRegular() {
					return nil
				}
				data, e := os.ReadFile(p)
				if e != nil {
					return e
				}
				if !bytes.Equal(data, raw) {
					return nil
				}
				found = true
				physical, e := filepath.EvalSymlinks(p)
				if e != nil {
					return e
				}
				rel, e := filepath.Rel(filepath.Join(real, "history"), physical)
				if e != nil {
					return e
				}
				if rel != ".." && (len(rel) < 3 || rel[:3] != ".."+string(filepath.Separator)) {
					t.Errorf("legacy bytes saved physically inside history: %s", physical)
				}
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
			if !found {
				t.Fatal("original backup bytes missing")
			}
		})
	}
}

// Additional coverage of an impossible external destination. No new repair or
// RED credit: the physical-placement fix already refuses this layout.
func TestUnsafeBackupFallbackRefusesWithoutRewritingHistory(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "history")
	if err := os.MkdirAll(dir, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(dir, dir+".schema7-text-backup"); err != nil {
		t.Fatal(err)
	}
	path := FactPath(dir, "01AAAAAAAAAAAAAAAAAAAAAAA1")
	raw := []byte(`{"id":"01AAAAAAAAAAAAAAAAAAAAAAA1","version":1,"created":"2026-01-01T00:00:00Z","status":"active","source":"user","content":"Keep original.","queries":["obsolete"]}` + "\n")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0600); err != nil {
		t.Fatal(err)
	}
	s, err := OpenText(dir, filepath.Join(dir, "cache.db"))
	if err == nil {
		_ = s.Close()
		t.Fatal("unsafe external backup fallback accepted")
	}
	got, err := os.ReadFile(path)
	if err != nil || !bytes.Equal(got, raw) {
		t.Fatalf("unsafe layout changed history: %v", err)
	}
}
