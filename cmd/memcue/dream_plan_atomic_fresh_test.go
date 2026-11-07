package main

import (
	"bytes"
	"reflect"
	"testing"
	"time"

	"github.com/juev/memcue/internal/extract"
)

func TestObsoleteDirectPlanRefusesBeforeAnyWrite(t *testing.T) {
	for _, kind := range []string{"expansion", "translation"} {
		t.Run(kind, func(t *testing.T) {
			dir := env(t)
			split := addFactForTest(t, "Copper uses port 5432; zinc uses port 6432.")
			corrected := addFactForTest(t, "Original separate observation.")
			beforeSplit, beforeCorrect := factHistory(t, split), factHistory(t, corrected)
			plan := dreamPlan{Start: time.Now(), Seen: map[string]int{}, Splits: []dreamPlanSplit{{ID: split, Version: 1, Parts: []string{"Copper uses port 5432.", "Zinc uses port 6432."}}}, Groups: []dreamPlanGroup{{Facts: map[string]int{corrected: 1}, Actions: []extract.Action{{Op: "correct", ID: corrected, Content: "Changed observation."}}}}}
			if kind == "expansion" {
				plan.Expansions = []dreamPlanExpansion{{ID: corrected, Version: 1, Queries: []string{"old query"}}}
			} else {
				plan.Translations = []dreamPlanTranslation{{ID: corrected, Version: 1, Translation: "old translation"}}
			}
			if _, err := applyPlan(dir, plan, dreamRecord{}, &bytes.Buffer{}); err == nil {
				t.Fatal("obsolete direct plan accepted")
			}
			if !reflect.DeepEqual(beforeSplit, factHistory(t, split)) || !reflect.DeepEqual(beforeCorrect, factHistory(t, corrected)) {
				t.Fatal("rejected obsolete plan changed fact history before refusal")
			}
			s, err := openBase()
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = s.Close() }()
			rows, err := s.Rows()
			if err != nil {
				t.Fatal(err)
			}
			if len(rows) != 2 {
				t.Fatalf("rejected plan left new facts: %d rows", len(rows))
			}
		})
	}
}
