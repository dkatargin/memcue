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

// Independent old writes can become identical after projection. Their original
// version numbers and auxiliary values distinguish writes before that loss.
func TestLegacyProjectedWritesConvergeWithoutLoss(t *testing.T) {
	const id = "01AAAAAAAAAAAAAAAAAAAAAAA1"
	oldLines := func(side string) []byte {
		var b bytes.Buffer
		keys := []string{"shared", side}
		if side == "left" {
			keys = append(keys, side)
		}
		for i, key := range keys {
			fmt.Fprintf(&b, `{"id":%q,"version":%d,"created":"2026-01-01T00:00:00Z","status":"active","author":"writer","content":"Порт PROJ-1234: 6432.","origin":"old","source":"user","kind":"environment","scope":"host:db","evidence":"fixture","review":"candidate","prompt_version":3,"channel":"knowledge","keywords":%q,"queries":"old query"}`+"\n", id, i+1, key)
		}
		return b.Bytes()
	}
	makeSQL := func(side string) string {
		t.Helper()
		path := contentLegacyBase(t)
		db, err := sql.Open("sqlite", path)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := db.Exec(`DELETE FROM facts`); err != nil {
			t.Fatal(err)
		}
		keys := []string{"shared", side}
		if side == "left" {
			keys = append(keys, side)
		}
		for i, key := range keys {
			_, err := db.Exec(`INSERT INTO facts(id,version,content,keywords,queries,origin,created,status,author,kind,scope,source,evidence,review,prompt_version,channel) VALUES (?,?,?,?,'old query','old','2026-01-01T00:00:00Z','active','writer','environment','host:db','user','fixture','candidate',3,'knowledge')`, id, i+1, "Порт PROJ-1234: 6432.", key)
			if err != nil {
				t.Fatal(err)
			}
		}
		if err := db.Close(); err != nil {
			t.Fatal(err)
		}
		return path
	}
	var canonical []byte
	for _, reverse := range []bool{false, true} {
		left, right := makeSQL("left"), makeSQL("right")
		if reverse {
			left, right = right, left
		}
		a, err := Open(left)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := a.Merge(right); err != nil {
			t.Fatal(err)
		}
		rows, err := a.History(id)
		if err != nil {
			t.Fatal(err)
		}
		if len(rows) != 4 {
			t.Fatalf("projected legacy writes lost: got %d versions, want 4", len(rows))
		}
		for i, f := range rows {
			if f.Version != i+1 || f.Content != "Порт PROJ-1234: 6432." || f.Author != "writer" || f.Origin != "old" || f.Source != "user" || f.Evidence != "fixture" || f.Channel != "knowledge" || f.Review != "candidate" || f.PromptVersion != 3 || f.Kind != "environment" || f.Scope != "host:db" {
				t.Fatalf("historical metadata changed: %+v", f)
			}
		}
		if _, err := a.Merge(right); err != nil {
			t.Fatal(err)
		}
		again, err := a.History(id)
		if err != nil || !reflect.DeepEqual(rows, again) {
			t.Fatalf("repeated merge changed history: %v", err)
		}
		if err := a.Close(); err != nil {
			t.Fatal(err)
		}
		a, err = Open(left)
		if err != nil {
			t.Fatal(err)
		}
		again, err = a.History(id)
		if err != nil || !reflect.DeepEqual(rows, again) {
			t.Fatalf("reopen changed history: %v", err)
		}
		if err := a.Close(); err != nil {
			t.Fatal(err)
		}
		b, err := Open(right)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := b.Merge(left); err != nil {
			t.Fatal(err)
		}
		converged, err := b.History(id)
		if err != nil || !reflect.DeepEqual(rows, converged) {
			t.Fatalf("offline convergence failed: %v", err)
		}
		if err := b.Close(); err != nil {
			t.Fatal(err)
		}
		encoded, err := EncodeFacts(rows)
		if err != nil {
			t.Fatal(err)
		}
		if canonical == nil {
			canonical = encoded
		} else if !bytes.Equal(canonical, encoded) {
			t.Fatal("merge orders disagree")
		}
	}
	// JSONL migration must establish exactly the same identities as SQLite.
	root := t.TempDir()
	histories := make([][]Fact, 2)
	for i, side := range []string{"left", "right"} {
		dir := filepath.Join(root, side)
		path := FactPath(dir, id)
		if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, oldLines(side), 0600); err != nil {
			t.Fatal(err)
		}
		s, err := OpenText(dir, filepath.Join(root, side+".db"))
		if err != nil {
			t.Fatal(err)
		}
		histories[i], err = s.History(id)
		if err != nil {
			t.Fatal(err)
		}
		if err := s.Close(); err != nil {
			t.Fatal(err)
		}
	}
	for _, sides := range [][2]int{{0, 1}, {1, 0}} {
		merged := MergeHistories(histories[sides[0]], histories[sides[1]]).Versions
		encoded, err := EncodeFacts(merged)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(encoded, canonical) {
			t.Fatalf("JSONL and SQLite projection disagree: %s", encoded)
		}
		if bytes.Contains(encoded, []byte("keywords")) || bytes.Contains(encoded, []byte("old query")) || bytes.Contains(encoded, []byte("queries")) {
			t.Fatal("auxiliary plaintext survived projection")
		}
	}
}
