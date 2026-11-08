package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func TestRepairUnavailableNativePitfalls(t *testing.T) {
	_, repo := pitfallFixture(t)
	t.Setenv("MEMCUE_POSTGRES_DSN", "invalid-explicit-remote")
	raw, _ := json.Marshal(sessionStartInput{CWD: repo, HookEventName: "PreToolUse"})
	var out bytes.Buffer
	if err := runSessionPitfalls(bytes.NewReader(raw), &out); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(out.String(), "No active repository pitfalls") || strings.Contains(out.String(), `"repositoryPitfallCount":0`) {
		t.Fatalf("failed remote read asserted authoritative emptiness: %s", out.String())
	}
	if !strings.Contains(out.String(), repositoryPitfallsUnavailable) {
		t.Fatal("unavailable marker missing")
	}
	if got := repositoryPitfalls(repo); strings.Contains(got, "No active repository pitfalls") {
		t.Fatal("session-start formatter asserted empty success")
	}
}
