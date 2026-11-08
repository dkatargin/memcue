package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/juev/memcue/internal/store"
)

func TestMalformedHookCannotSelectRepository(t *testing.T) {
	_, repo := pitfallFixture(t)
	fact := putPitfall(t, "Synthetic partial-input pitfall must only apply to the selected repository.", "", store.Meta{Kind: "pitfall", Scope: "repo:example.invalid/team/repo"})
	raw, _ := json.Marshal(repo)
	input := `{"cwd":` + string(raw) + `,}`
	var baseline sessionStartInput
	if e := json.NewDecoder(strings.NewReader(input)).Decode(&baseline); e == nil || baseline.CWD != "" {
		t.Fatal("standard malformed-hook baseline changed")
	}
	inv := newInvocation()
	defer inv.close()
	var out bytes.Buffer
	if e := inv.runSessionStartWith(strings.NewReader(input), &out, 1, true); e != nil {
		t.Fatal(e)
	}
	if strings.Contains(out.String(), fact.Content) {
		t.Fatal("malformed hook supplied partial cwd and repository hints")
	}
	// The optional-input error convention still produces instructions; valid input selects the repo.
	if !strings.Contains(out.String(), "Long-term memory") {
		t.Fatal("optional malformed input suppressed instructions")
	}
	out.Reset()
	if e := inv.runSessionStartWith(strings.NewReader(`{"cwd":`+string(raw)+`}`), &out, 1, true); e != nil {
		t.Fatal(e)
	}
	if !strings.Contains(out.String(), fact.Content) {
		t.Fatal("valid hook lost repository hints")
	}
}
