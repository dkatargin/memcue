package main

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

type failedPullOutput struct{ bytes int }

func (w *failedPullOutput) Write(p []byte) (int, error) {
	n := len(p) / 2
	w.bytes += n
	return n, errors.New("synthetic broken output")
}

func TestPreCommandReservesBeforeOutputFailure(t *testing.T) {
	dir := env(t)
	if err := os.MkdirAll(filepath.Join(dir, ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, ".git/config"), []byte("[remote \"origin\"]\nurl = https://synthetic.invalid/orchard.git\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	addFactForTest(t, "-cwd", dir, "-kind", "pitfall", "-scope", "repo", "Orchard build requires amber mode only for synthetic fixtures.")
	args := []string{"-cwd", dir, "-session", "synthetic-output-failure", "-action", "build", "orchard build"}
	writer := &failedPullOutput{}
	for range 100 {
		if err := runPreCommand(args, writer); err == nil {
			t.Fatal("expected failed output or exhausted budget")
		}
	}
	data, err := os.ReadFile(filepath.Join(os.Getenv("MEMCUE_STATE_DIR"), "pre-command.json"))
	if err != nil {
		t.Fatalf("failed output lost reserved accounting: %v", err)
	}
	var state pullState
	if err := json.Unmarshal(data, &state); err != nil {
		t.Fatal(err)
	}
	task := state.Tasks[pullHash("synthetic-output-failure")]
	if task == nil || task.Spent <= pullInstructionBytes || task.Spent > pullTaskBytes {
		t.Fatalf("reservation not conservative: %+v", task)
	}
	if writer.bytes > pullTaskBytes {
		t.Fatalf("failed output escaped cap: %d", writer.bytes)
	}
	t.Logf("partial output=%d bytes, reserved=%d bytes", writer.bytes, task.Spent)
}
