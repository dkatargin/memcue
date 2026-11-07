package store

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

const r5ID = "01AAAAAAAAAAAAAAAAAAAAAAA1"

var r5EmptyForms = []struct{ name, fields string }{
	{"arrays", `,"keywords":[],"queries":[]`},
	{"keywords-only", `,"keywords":[]`},
	{"queries-only", `,"queries":[]`},
	{"nulls", `,"keywords":null,"queries":null`},
	{"scalar-empty", `,"keywords":"","queries":""`},
	{"empty-items", `,"keywords":[""],"queries":[""]`},
	{"keyword-null-query-array", `,"keywords":null,"queries":[]`},
	{"keyword-array-query-null", `,"keywords":[],"queries":null`},
}

var r5Classes = [][]string{{"empty", "empty"}, {"empty", "empty", "empty"}, {"empty", "keyword", "empty", "query", "empty", "keyword", "both", "both"}}

// A literal published schema-7 fixture supplies an independent representation
// of each recorded write. All remaining text and metadata deliberately agree.
func r5LegacySQL(t *testing.T, classes []string) string {
	t.Helper()
	path := contentLegacyBase(t)
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`DELETE FROM facts`); err != nil {
		t.Fatal(err)
	}
	for i, class := range classes {
		keyword, query := "", ""
		if class == "keyword" || class == "both" {
			keyword = "r5legacykeyword"
		}
		if class == "query" || class == "both" {
			query = "r5legacyquery"
		}
		_, err := db.Exec(`INSERT INTO facts(id,version,content,keywords,queries,origin,created,status,author,expires,kind,scope,source,evidence,review,prompt_version,channel) VALUES (?,?,?, ?,?,'fixture','2026-01-01T00:00:00Z','active','writer','2030-01-01','environment','host:fixture','user','evidence','candidate',3,'knowledge')`, r5ID, i+1, "Порт PROJ-5678 равен 6432.", keyword, query)
		if err != nil {
			t.Fatal(err)
		}
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func r5SQLRows(t *testing.T, path string) []Fact {
	t.Helper()
	s, err := OpenReadOnly(path)
	if err != nil {
		t.Fatal(err)
	}
	rows, err := s.History(r5ID)
	if err != nil {
		t.Fatal(err)
	}
	if err := s.Close(); err != nil {
		t.Fatal(err)
	}
	return rows
}

// Empty fields alternate between omission and a supplied accepted encoding.
// Nonempty auxiliary classes and already persisted identities must not consume
// one another's occurrence ranks. Physical line order and append retries do
// not change the logical version sequence.
func r5JSONL(t *testing.T, classes []string, form string, swap, reverse, persistMiddle bool, want []Fact) []byte {
	t.Helper()
	var lines [][]byte
	empty := 0
	for i, class := range classes {
		fields := ""
		if class == "empty" {
			explicit := empty%2 == 1
			if swap {
				explicit = !explicit
			}
			if explicit {
				fields = form
			}
			empty++
		} else {
			keyword, query := "", ""
			if class == "keyword" || class == "both" {
				keyword = "r5legacykeyword"
			}
			if class == "query" || class == "both" {
				query = "r5legacyquery"
			}
			fields = fmt.Sprintf(`,"keywords":[%q],"queries":[%q]`, keyword, query)
		}
		if persistMiddle && i == 1 && class == "empty" {
			fields = fmt.Sprintf(`,"write_id":%q`, want[i].WriteID)
		}
		line := fmt.Sprintf(`{"id":%q,"version":%d,"content":"Порт PROJ-5678 равен 6432.","origin":"fixture","created":"2026-01-01T00:00:00Z","status":"active","author":"writer","expires":"2030-01-01","kind":"environment","scope":"host:fixture","source":"user","evidence":"evidence","review":"candidate","prompt_version":3,"channel":"knowledge"%s}`+"\n", r5ID, i+1, fields)
		if !json.Valid(bytes.TrimSpace([]byte(line))) {
			t.Fatal("invalid fixture JSON")
		}
		lines = append(lines, []byte(line))
	}
	if reverse {
		for i, j := 0, len(lines)-1; i < j; i, j = i+1, j-1 {
			lines[i], lines[j] = lines[j], lines[i]
		}
	}
	// A byte-identical append retry is one version, not another occurrence.
	lines = append(lines, lines[len(lines)-1])
	return bytes.Join(lines, nil)
}

func TestR5MixedEmptyEncodingsAgreeWithSQLite(t *testing.T) {
	for _, classes := range r5Classes {
		path := r5LegacySQL(t, classes)
		want := r5SQLRows(t, path)
		if len(want) != len(classes) {
			t.Fatal("fixture lost recorded SQLite versions")
		}
		for _, form := range r5EmptyForms {
			for _, swap := range []bool{false, true} {
				for _, reverse := range []bool{false, true} {
					for _, persist := range []bool{false, true} {
						if persist && len(classes) != 3 {
							continue
						}
						t.Run(fmt.Sprintf("%d/%s/%v/%v/persist=%v", len(classes), form.name, swap, reverse, persist), func(t *testing.T) {
							rows, err := ParseFacts(r5JSONL(t, classes, form.fields, swap, reverse, persist, want))
							if err != nil {
								t.Fatal(err)
							}
							if !reflect.DeepEqual(rows, want) {
								t.Errorf("equivalent empty encodings assigned incompatible complete-history identities: %d JSONL rows, %d SQLite rows", len(rows), len(want))
							}
							for _, sides := range [][2][]Fact{{rows, want}, {want, rows}} {
								merged := MergeHistories(sides[0], sides[1]).Versions
								if !reflect.DeepEqual(merged, want) {
									t.Errorf("equivalent histories invented or lost versions: got %d want %d", len(merged), len(want))
									continue
								}
								if again := MergeHistories(merged, sides[1]).Versions; !reflect.DeepEqual(again, want) {
									t.Error("repeated merge changed canonical occurrences")
								}
							}
							encoded, err := EncodeFacts(rows)
							if err != nil {
								t.Fatal(err)
							}
							again, err := ParseFacts(encoded)
							if err != nil || !reflect.DeepEqual(rows, again) {
								t.Fatalf("current round trip changed identities: %v", err)
							}
						})
					}
				}
			}
		}
	}
}

func TestR5MixedEmptyCacheAndStoreMergeStayIdempotent(t *testing.T) {
	for _, classes := range r5Classes {
		original := r5LegacySQL(t, classes)
		want := r5SQLRows(t, original)
		oldBytes, err := os.ReadFile(original)
		if err != nil {
			t.Fatal(err)
		}
		for _, form := range r5EmptyForms {
			for _, swap := range []bool{false, true} {
				for _, reverseMerge := range []bool{false, true} {
					t.Run(fmt.Sprintf("%d/%s/%v/%v", len(classes), form.name, swap, reverseMerge), func(t *testing.T) {
						root := t.TempDir()
						dir := filepath.Join(root, "history")
						cache := filepath.Join(root, "cache.db")
						other := filepath.Join(root, "original.db")
						if err := os.WriteFile(cache, oldBytes, 0600); err != nil {
							t.Fatal(err)
						}
						if err := os.WriteFile(other, oldBytes, 0600); err != nil {
							t.Fatal(err)
						}
						path := FactPath(dir, r5ID)
						if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
							t.Fatal(err)
						}
						if err := os.WriteFile(path, r5JSONL(t, classes, form.fields, swap, true, false, want), 0600); err != nil {
							t.Fatal(err)
						}
						text, err := OpenText(dir, cache)
						if err != nil {
							t.Fatal(err)
						}
						if reverseMerge {
							peer, err := Open(other)
							if err != nil {
								t.Fatal(err)
							}
							if _, err := peer.Merge(cache); err != nil {
								t.Fatal(err)
							}
							got, err := peer.History(r5ID)
							if err != nil {
								t.Fatal(err)
							}
							if !reflect.DeepEqual(got, want) {
								t.Errorf("actual reverse Store.Merge invented history: got %d want %d", len(got), len(want))
							}
							if err := peer.Close(); err != nil {
								t.Fatal(err)
							}
						}
						for attempt := 0; attempt < 2; attempt++ {
							if _, err := text.Merge(other); err != nil {
								t.Fatal(err)
							}
							got, err := text.History(r5ID)
							if err != nil {
								t.Fatal(err)
							}
							if !reflect.DeepEqual(got, want) {
								t.Errorf("actual cache/Store.Merge changed recorded writes on attempt %d: got %d want %d", attempt, len(got), len(want))
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
							t.Errorf("reopen retained invented or lost history: %v; %d rows want %d", err, len(got), len(want))
						}
						disk, err := ReadFactFile(path)
						if err != nil || !reflect.DeepEqual(disk, want) {
							t.Errorf("JSONL/cache/SQLite disagree after reopen: %v", err)
						}
						current, err := os.ReadFile(path)
						if err != nil {
							t.Fatal(err)
						}
						if bytes.Contains(current, []byte("r5legacykeyword")) || bytes.Contains(current, []byte("r5legacyquery")) || bytes.Contains(current, []byte("keywords")) || bytes.Contains(current, []byte("queries")) {
							t.Error("auxiliary plaintext survived in current history")
						}
					})
				}
			}
		}
	}
}

// Redundant accepted empty fields must not turn a stored identity into another
// event. This includes current rows whose identity originally represented a
// nonempty auxiliary class: projection has already removed those old values.
func TestR5EmptyFieldsPreserveAlreadyStoredIdentities(t *testing.T) {
	for _, classes := range r5Classes {
		original := r5LegacySQL(t, classes)
		want := r5SQLRows(t, original)
		encoded, err := EncodeFacts(want)
		if err != nil {
			t.Fatal(err)
		}
		for _, form := range r5EmptyForms {
			for _, swap := range []bool{false, true} {
				for _, reverse := range []bool{false, true} {
					t.Run(fmt.Sprintf("%d/%s/%v/%v", len(classes), form.name, swap, reverse), func(t *testing.T) {
						var added map[string]json.RawMessage
						if err := json.Unmarshal([]byte("{"+form.fields[1:]+"}"), &added); err != nil {
							t.Fatal(err)
						}
						var lines [][]byte
						for i, line := range bytes.Split(bytes.TrimSpace(encoded), []byte("\n")) {
							var row map[string]json.RawMessage
							if err := json.Unmarshal(line, &row); err != nil {
								t.Fatal(err)
							}
							if (i%2 == 0) != swap {
								for key, value := range added {
									row[key] = value
								}
							}
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
						got, err := ParseFacts(bytes.Join(lines, nil))
						if err != nil {
							t.Fatal(err)
						}
						if !reflect.DeepEqual(got, want) {
							t.Error("accepted empty fields changed already stored identities")
						}
						for _, sides := range [][2][]Fact{{got, want}, {want, got}} {
							merged := MergeHistories(sides[0], sides[1]).Versions
							if !reflect.DeepEqual(merged, want) {
								t.Errorf("redundant empty fields invented history: got %d want %d", len(merged), len(want))
							}
						}
					})
				}
			}
		}
	}
}
