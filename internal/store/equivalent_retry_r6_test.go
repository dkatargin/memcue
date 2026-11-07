package store

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

var r6Forms = []map[string]any{
	{}, {"keywords": []string{}, "queries": []string{}}, {"keywords": []string{}}, {"queries": []string{}},
	{"keywords": nil, "queries": nil}, {"keywords": "", "queries": ""}, {"keywords": []string{""}, "queries": []string{""}},
	{"keywords": nil, "queries": []string{}}, {"keywords": []string{}, "queries": nil},
}

func r6Row(version int, class string, empty map[string]any, identity string) map[string]any {
	row := map[string]any{"id": r5ID, "version": version, "content": "Порт PROJ-5678 равен 6432.", "origin": "fixture", "created": "2026-01-01T00:00:00Z", "status": "active", "author": "writer", "expires": "2030-01-01", "kind": "environment", "scope": "host:fixture", "source": "user", "evidence": "evidence", "review": "candidate", "prompt_version": 3, "channel": "knowledge"}
	for key, value := range empty {
		row[key] = value
	}
	if class == "keyword" {
		row["keywords"] = []string{"r5legacykeyword"}
	}
	if class == "query" {
		row["queries"] = []string{"r5legacyquery"}
	}
	if identity != "" {
		row["write_id"] = identity
	}
	return row
}

func r6Document(t *testing.T, rows []map[string]any, reverse bool) []byte {
	t.Helper()
	var lines [][]byte
	for _, row := range rows {
		data, err := json.Marshal(row)
		if err != nil {
			t.Fatal(err)
		}
		lines = append(lines, append(data, '\n'))
	}
	if reverse {
		for i, j := 0, len(lines)-1; i < j; i, j = i+1, j-1 {
			lines[i], lines[j] = lines[j], lines[i]
		}
	}
	return bytes.Join(lines, nil)
}

func r6Retries(classes []string, one, two map[string]any, identities []Fact, stored bool) []map[string]any {
	var rows []map[string]any
	for i, class := range classes {
		identity := ""
		if stored {
			identity = identities[i].WriteID
		}
		rows = append(rows, r6Row(i+1, class, one, ""), r6Row(i+1, class, two, identity), r6Row(i+1, class, one, ""))
	}
	return rows
}

func TestR6EquivalentRetriesPrecedeOccurrenceCounting(t *testing.T) {
	for _, classes := range [][]string{{"empty"}, {"empty", "keyword", "empty", "empty", "query"}} {
		original := r5LegacySQL(t, classes)
		want := r5SQLRows(t, original)
		for a, one := range r6Forms {
			for b, two := range r6Forms {
				for _, stored := range []bool{false, true} {
					for _, reverse := range []bool{false, true} {
						t.Run(fmt.Sprintf("%d/%d-%d/stored=%v/reverse=%v", len(classes), a, b, stored, reverse), func(t *testing.T) {
							raw := r6Document(t, r6Retries(classes, one, two, want, stored), reverse)
							got, err := ParseFacts(raw)
							if err != nil {
								t.Fatalf("equivalent same-version retries falsely conflict: %v", err)
							}
							if len(got) != len(classes) {
								t.Fatalf("retry count changed distinct-version multiplicity: got %d want %d", len(got), len(classes))
							}
							for _, sides := range [][2][]Fact{{got, want}, {want, got}} {
								merged := MergeHistories(sides[0], sides[1]).Versions
								if !reflect.DeepEqual(merged, want) {
									t.Fatalf("canonical retry history differs from SQLite: got %+v want %+v", merged, want)
								}
								if again := MergeHistories(merged, sides[1]).Versions; !reflect.DeepEqual(again, want) {
									t.Fatal("retry merge was not idempotent")
								}
							}
							current, err := EncodeFacts(got)
							if err != nil {
								t.Fatal(err)
							}
							again, err := ParseFacts(current)
							if err != nil || !reflect.DeepEqual(again, got) {
								t.Fatalf("current roundtrip changed canonical versions: %v", err)
							}
						})
					}
				}
			}
		}
	}
}

func TestR6DifferentSameVersionRecordsStillConflict(t *testing.T) {
	fixture := r5LegacySQL(t, []string{"empty", "empty"})
	ids := r5SQLRows(t, fixture)
	cases := []struct {
		name, key string
		value     any
	}{
		{"content", "content", "Different literal content."}, {"source", "source", "tool"}, {"evidence", "evidence", "different evidence"},
		{"expiry", "expires", "2031-01-01"}, {"origin", "origin", "other"}, {"author", "author", "other writer"}, {"time", "created", "2026-01-02T00:00:00Z"},
		{"status", "status", Retired}, {"kind", "kind", "rule"}, {"scope", "scope", "global"}, {"review", "review", ""}, {"prompt", "prompt_version", 4}, {"channel", "channel", "behaviour"},
		{"nonempty-keywords", "keywords", []string{"different keyword"}}, {"nonempty-queries", "queries", []string{"different query"}},
	}
	for _, test := range cases {
		for _, reverse := range []bool{false, true} {
			t.Run(fmt.Sprintf("%s/%v", test.name, reverse), func(t *testing.T) {
				one := r6Row(1, "empty", r6Forms[0], "")
				two := r6Row(1, "empty", r6Forms[1], "")
				two[test.key] = test.value
				if _, err := ParseFacts(r6Document(t, []map[string]any{one, two}, reverse)); err == nil {
					t.Fatal("genuinely different same-version records were accepted")
				}
			})
		}
	}
	for _, key := range []string{"keywords", "queries"} {
		for _, reverse := range []bool{false, true} {
			one, two := r6Row(1, "empty", r6Forms[0], ""), r6Row(1, "empty", r6Forms[0], "")
			one[key] = []string{"first"}
			two[key] = []string{"second"}
			if _, err := ParseFacts(r6Document(t, []map[string]any{one, two}, reverse)); err == nil {
				t.Fatalf("different nonempty %s values collapsed", key)
			}
		}
	}
	for _, reverse := range []bool{false, true} {
		one, two := r6Row(1, "empty", r6Forms[0], ids[0].WriteID), r6Row(1, "empty", r6Forms[1], ids[1].WriteID)
		if _, err := ParseFacts(r6Document(t, []map[string]any{one, two}, reverse)); err == nil {
			t.Fatal("different stored identities at one version were ignored")
		}
		two["write_id"] = ids[0].WriteID
		two["keywords"] = []string{"not the stored identity's auxiliary class"}
		if _, err := ParseFacts(r6Document(t, []map[string]any{one, two}, reverse)); err == nil {
			t.Fatal("nonempty auxiliary conflict hidden by a shared stored identity")
		}
	}
}

func TestR6EquivalentRetriesOpenAndMerge(t *testing.T) {
	for _, classes := range [][]string{{"empty"}, {"empty", "keyword", "empty", "empty", "query"}} {
		original := r5LegacySQL(t, classes)
		want := r5SQLRows(t, original)
		old, err := os.ReadFile(original)
		if err != nil {
			t.Fatal(err)
		}
		for form, empty := range r6Forms {
			for _, cacheExists := range []bool{false, true} {
				for _, reverse := range []bool{false, true} {
					t.Run(fmt.Sprintf("%d/form=%d/cache=%v/reverse=%v", len(classes), form, cacheExists, reverse), func(t *testing.T) {
						root := t.TempDir()
						dir, cache, peerPath := filepath.Join(root, "history"), filepath.Join(root, "cache.db"), filepath.Join(root, "peer.db")
						if cacheExists {
							if err := os.WriteFile(cache, old, 0600); err != nil {
								t.Fatal(err)
							}
						}
						if err := os.WriteFile(peerPath, old, 0600); err != nil {
							t.Fatal(err)
						}
						path := FactPath(dir, r5ID)
						if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
							t.Fatal(err)
						}
						raw := r6Document(t, r6Retries(classes, r6Forms[0], empty, want, true), reverse)
						if err := os.WriteFile(path, raw, 0600); err != nil {
							t.Fatal(err)
						}
						text, err := OpenText(dir, cache)
						if err != nil {
							t.Fatalf("OpenText refused a valid equivalent append retry: %v", err)
						}
						if reverse {
							peer, err := Open(peerPath)
							if err != nil {
								t.Fatal(err)
							}
							if _, err := peer.Merge(cache); err != nil {
								t.Fatal(err)
							}
							got, err := peer.History(r5ID)
							if err != nil || !reflect.DeepEqual(got, want) {
								t.Fatalf("reverse SQLite merge changed retry history: %v", err)
							}
							if err := peer.Close(); err != nil {
								t.Fatal(err)
							}
						}
						for attempt := 0; attempt < 2; attempt++ {
							if _, err := text.Merge(peerPath); err != nil {
								t.Fatal(err)
							}
							got, err := text.History(r5ID)
							if err != nil || !reflect.DeepEqual(got, want) {
								t.Fatalf("cache/text merge changed versions on attempt %d: %v; %+v", attempt, err, got)
							}
						}
						if err := text.Close(); err != nil {
							t.Fatal(err)
						}
						text, err = OpenText(dir, cache)
						if err != nil {
							t.Fatal(err)
						}
						defer func() { _ = text.Close() }()
						got, err := text.History(r5ID)
						if err != nil || !reflect.DeepEqual(got, want) {
							t.Fatalf("reopen changed retry history: %v", err)
						}
						disk, err := ReadFactFile(path)
						if err != nil || !reflect.DeepEqual(disk, want) {
							t.Fatalf("disk/cache/SQLite disagree: %v", err)
						}
						data, err := os.ReadFile(path)
						if err != nil {
							t.Fatal(err)
						}
						if bytes.Contains(data, []byte("keywords")) || bytes.Contains(data, []byte("queries")) || bytes.Contains(data, []byte("r5legacy")) {
							t.Fatal("auxiliary plaintext retained in current history")
						}
					})
				}
			}
		}
	}
}
