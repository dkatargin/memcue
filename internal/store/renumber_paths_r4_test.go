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

// Exercise the same retired lineage at real boundaries, including a repeated
// fully equal legacy write. Its occurrence number, unlike the version, stays
// unchanged when other writes have already been merged before it.
func TestR4RenumberedHistoryAcrossStoragePaths(t *testing.T) {
	for _, positions := range [][]int{{0, 1, 2}, {0, 1, 2, 3, 4}, {0, 1, 2, 2, 3, 4}} {
		stale := []int{0, 2}
		if len(positions) == 6 {
			stale = []int{0, 2, 2}
		}
		for _, mode := range []string{"sqlite", "cache", "text"} {
			for _, reverse := range []bool{false, true} {
				t.Run(fmt.Sprintf("%d/%s/%v", len(positions), mode, reverse), func(t *testing.T) {
					a, b := r4LegacyHistory(t, positions), r4LegacyHistory(t, stale)
					root := t.TempDir()
					// Build published JSONL independently from literal old SQLite columns,
					// not by encoding the candidate's already-projected Fact model.
					writeOldText := func(dbPath, dir string) {
						t.Helper()
						db, err := sql.Open("sqlite", dbPath)
						if err != nil {
							t.Fatal(err)
						}
						rows, err := db.Query(`SELECT id,version,created,status,author,content,origin,expires,kind,scope,source,evidence,review,prompt_version,channel,keywords,queries FROM facts ORDER BY id,version`)
						if err != nil {
							t.Fatal(err)
						}
						var data bytes.Buffer
						for rows.Next() {
							var id, created, status, author, content, origin, expires, kind, scope, source, evidence, review, channel, kw, qu string
							var version, prompt int
							if err := rows.Scan(&id, &version, &created, &status, &author, &content, &origin, &expires, &kind, &scope, &source, &evidence, &review, &prompt, &channel, &kw, &qu); err != nil {
								t.Fatal(err)
							}
							fmt.Fprintf(&data, `{"id":%q,"version":%d,"created":%q,"status":%q,"author":%q,"content":%q,"origin":%q,"expires":%q,"kind":%q,"scope":%q,"source":%q,"evidence":%q,"review":%q,"prompt_version":%d,"channel":%q,"keywords":[%q],"queries":[%q]}`+"\n", id, version, created, status, author, content, origin, expires, kind, scope, source, evidence, review, prompt, channel, kw, qu)
						}
						if err := rows.Err(); err != nil {
							t.Fatal(err)
						}
						if err := rows.Close(); err != nil {
							t.Fatal(err)
						}
						if err := db.Close(); err != nil {
							t.Fatal(err)
						}
						path := FactPath(dir, r4FactID)
						if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
							t.Fatal(err)
						}
						if err := os.WriteFile(path, data.Bytes(), 0600); err != nil {
							t.Fatal(err)
						}
					}
					complete, err := OpenReadOnly(a)
					if err != nil {
						t.Fatal(err)
					}
					want, err := complete.History(r4FactID)
					if err != nil {
						t.Fatal(err)
					}
					if err := complete.Close(); err != nil {
						t.Fatal(err)
					}
					var s *Store
					path, other := a, b
					peerText := ""
					switch mode {
					case "sqlite":
						if reverse {
							path, other = b, a
						}
						s, err = Open(path)
						if err == nil {
							_, err = s.Merge(other)
						}
					case "cache":
						dir := filepath.Join(root, "history")
						file, cache := a, b
						if reverse {
							file, cache = b, a
						}
						writeOldText(file, dir)
						path = cache
						s, err = OpenText(dir, cache)
					case "text":
						da, db := filepath.Join(root, "a"), filepath.Join(root, "b")
						writeOldText(a, da)
						writeOldText(b, db)
						left, right := filepath.Join(root, "a.db"), filepath.Join(root, "b.db")
						one, e := OpenText(da, left)
						if e != nil {
							t.Fatal(e)
						}
						if e := one.Close(); e != nil {
							t.Fatal(e)
						}
						two, e := OpenText(db, right)
						if e != nil {
							t.Fatal(e)
						}
						if e := two.Close(); e != nil {
							t.Fatal(e)
						}
						if reverse {
							da, db = db, da
							left, right = right, left
						}
						path, other = left, right
						peerText = db
						s, err = OpenText(da, left)
						if err == nil {
							_, err = s.Merge(right)
						}
					}
					if err != nil {
						t.Fatal(err)
					}
					got, err := s.History(r4FactID)
					if err != nil {
						t.Fatal(err)
					}
					if !reflect.DeepEqual(got, want) {
						t.Fatalf("known lineage changed (%s):\ngot %+v\nwant %+v", mode, got, want)
					}
					// Repeated source merge, reopen, and the reverse offline merge must
					// converge on the complete version sequence, metadata and status.
					if mode == "cache" {
						other = r4LegacyHistory(t, stale)
					}
					if _, err := s.Merge(other); err != nil {
						t.Fatal(err)
					}
					text := s.Text()
					if err := s.Close(); err != nil {
						t.Fatal(err)
					}
					if text != "" {
						s, err = OpenText(text, path)
					} else {
						s, err = Open(path)
					}
					if err != nil {
						t.Fatal(err)
					}
					got, err = s.History(r4FactID)
					if err != nil || !reflect.DeepEqual(got, want) {
						t.Fatalf("repeated merge/reopen changed lineage: %v", err)
					}
					if text != "" {
						disk, err := ReadFactFile(FactPath(text, r4FactID))
						if err != nil || !reflect.DeepEqual(disk, want) {
							t.Fatalf("text/cache disagree: %v", err)
						}
					}
					if err := s.Close(); err != nil {
						t.Fatal(err)
					}
					var peer *Store
					if peerText != "" {
						peer, err = OpenText(peerText, other)
					} else {
						peer, err = Open(other)
					}
					if err != nil {
						t.Fatal(err)
					}
					if _, err := peer.Merge(path); err != nil {
						t.Fatal(err)
					}
					converged, err := peer.History(r4FactID)
					if err != nil || !reflect.DeepEqual(converged, want) {
						t.Fatalf("offline merge disagrees: %v", err)
					}
					if err := peer.Close(); err != nil {
						t.Fatal(err)
					}
					if peerText != "" {
						peer, err = OpenText(peerText, other)
						if err != nil {
							t.Fatal(err)
						}
						disk, err := ReadFactFile(FactPath(peerText, r4FactID))
						if err != nil || !reflect.DeepEqual(disk, want) {
							t.Fatalf("offline text peer did not converge: %v", err)
						}
						if err := peer.Close(); err != nil {
							t.Fatal(err)
						}
					}
					data, err := EncodeFacts(got)
					if err != nil {
						t.Fatal(err)
					}
					if bytes.Contains(data, []byte("legacy markers")) || bytes.Contains(data, []byte("old query")) || bytes.Contains(data, []byte("keywords")) || bytes.Contains(data, []byte("queries")) {
						t.Fatal("auxiliary plaintext entered current history")
					}
				})
			}
		}
	}
}
