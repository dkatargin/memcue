package store

import (
	"crypto/sha256"
	"database/sql"
	"encoding/json"
	"fmt"
)

// The digest is operational metadata, never search text. Establish it before
// discarding auxiliary fields. Version numbers are mutable merge positions,
// so repeated equal rows receive occurrence identities over the complete history.
func projectedWriteID(f Fact, keywords, queries string) string {
	// Optional labels did not exist in every old cache schema. They remain
	// part of equality, but cannot define the underlying write's identity.
	f.Version = 0
	f.Expires = ""
	f.Meta = Meta{}
	line, _ := encodeLine(f)
	data, _ := json.Marshal([]string{string(line), keywords, queries})
	return fmt.Sprintf("%x", sha256.Sum256(data))
}

func (s *Store) scanLegacy(row interface{ Scan(...any) error }) (Fact, error) {
	if !s.legacy["keywords"] && !s.legacy["queries"] {
		return scan(row)
	}
	var kw, qu string
	f, err := scan(row, &kw, &qu)
	if err == nil {
		f.WriteID = projectedWriteID(f, kw, qu)
		if id, ok := s.legacyIDs[legacyVersion{f.ID, f.Version}]; ok {
			f.WriteID = id
		}
	}
	return f, err
}

func (s *Store) queryLegacy(db interface {
	Query(string, ...any) (*sql.Rows, error)
}, q string, args ...any) ([]Fact, error) {
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	var out []Fact
	for rows.Next() {
		f, err := s.scanLegacy(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, f)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if (s.legacy["keywords"] || s.legacy["queries"]) && s.legacyIDs == nil {
		s.legacyIDs = map[legacyVersion]string{}
		counts := map[string]int{}
		for i, f := range out {
			key := legacyOccurrenceKey(f)
			counts[key]++
			out[i].WriteID = legacyOccurrenceID(f.WriteID, counts[key])
			s.legacyIDs[legacyVersion{f.ID, f.Version}] = out[i].WriteID
		}
	}
	return out, nil
}

// Occurrences count only fully equal legacy records, not rows that merely have
// the same projected text. Their order survives insertion of other writes.
type legacyVersion struct {
	id      string
	version int
}

func legacyOccurrenceKey(f Fact) string {
	f.Version = 0
	line, _ := encodeLine(f)
	return string(line)
}

func legacyOccurrenceID(base string, occurrence int) string {
	if occurrence <= 1 {
		return base
	}
	return fmt.Sprintf("%s.%020d", base, occurrence)
}
