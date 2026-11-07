package store

import (
	"reflect"
	"testing"
)

func TestR4DoubleDigitOccurrencesKeepKnownSequence(t *testing.T) {
	complete, stale := []int{0, 1}, []int{0}
	for i := 0; i < 12; i++ {
		complete = append(complete, 2)
		stale = append(stale, 2)
	}
	complete = append(complete, 3, 4)
	a, b := r4LegacyHistory(t, complete), r4LegacyHistory(t, stale)
	s, err := Open(a)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	want, err := s.History(r4FactID)
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
	if !reflect.DeepEqual(got, want) {
		t.Fatal("known repeated writes changed their recorded sequence after merging the renumbered stale copy")
	}
	if got[len(got)-1].Status != Retired {
		t.Fatal("known repeated correction resurrected after retirement")
	}
}
