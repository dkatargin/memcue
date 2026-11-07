package store

import (
	"database/sql"
	"fmt"
	"reflect"
	"testing"
)

const r4FactID = "01AAAAAAAAAAAAAAAAAAAAAAA1"

// These are published schema-7 rows, before any operational identity existed.
// The same January 3 write has number 3 after a legacy merge, and number 2 on
// the stale machine. The later correction and retirement already observed it.
func r4LegacyHistory(t *testing.T, positions []int) string {
	t.Helper()
	path := contentLegacyBase(t)
	db, err := sql.Open("sqlite", path)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := db.Exec(`DELETE FROM facts`); err != nil {
		t.Fatal(err)
	}
	contents := []string{"Initial observation.", "Left observation.", "Right observation.", "Final observation.", "Final observation."}
	for version, position := range positions {
		status := Active
		if position == 4 {
			status = Retired
		}
		_, err := db.Exec(`INSERT INTO facts(id,version,content,keywords,queries,origin,created,status,author,expires,kind,scope,source,evidence,review,prompt_version,channel) VALUES (?,?,?,'legacy markers','old query','fixture',?,?, 'writer','2030-01-01','environment','host:fixture','user','evidence','candidate',3,'knowledge')`, r4FactID, version+1, contents[position], fmt.Sprintf("2026-01-%02dT00:00:00Z", position+1), status)
		if err != nil {
			t.Fatal(err)
		}
	}
	if err := db.Close(); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestR4RenumberedKnownCorrectionKeepsRetirement(t *testing.T) {
	for _, reverse := range []bool{false, true} {
		t.Run(fmt.Sprint(reverse), func(t *testing.T) {
			a, b := r4LegacyHistory(t, []int{0, 1, 2, 3, 4}), r4LegacyHistory(t, []int{0, 2})
			complete, err := Open(a)
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
			if reverse {
				a, b = b, a
			}
			s, err := Open(a)
			if err != nil {
				t.Fatal(err)
			}
			if _, err := s.Merge(b); err != nil {
				t.Fatal(err)
			}
			got, err := s.History(r4FactID)
			if err != nil {
				t.Fatal(err)
			}
			if len(got) != 5 || got[len(got)-1].Status != Retired {
				t.Fatalf("known renumbered correction duplicated or resurrected: %d versions, latest %+v", len(got), got[len(got)-1])
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("known history changed:\ngot %+v\nwant %+v", got, want)
			}
			if _, err := s.Merge(b); err != nil {
				t.Fatal(err)
			}
			if err := s.Close(); err != nil {
				t.Fatal(err)
			}
			s, err = Open(a)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = s.Close() }()
			again, err := s.History(r4FactID)
			if err != nil || !reflect.DeepEqual(got, again) {
				t.Fatalf("repeated merge/reopen changed history: %v", err)
			}
		})
	}
}
