package tailnet

import (
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func TestAcquireRejectsExistingExposedNodeState(t *testing.T) {
	dir := privateFixtureDir(t)
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	statePath := filepath.Join(dir, "tailscaled.state")
	if err := os.WriteFile(statePath, []byte("synthetic node identity fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(statePath, 0644); err != nil {
		t.Fatal(err)
	}
	root, err := os.Lstat(dir)
	if err != nil {
		t.Fatal(err)
	}
	if !root.IsDir() || root.Mode().Perm() != 0700 {
		t.Fatalf("fixture root must be a private directory: %v", root.Mode())
	}
	owner, ok := root.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
		t.Fatal("fixture root must belong to the effective user")
	}
	state, err := os.Lstat(statePath)
	if err != nil {
		t.Fatal(err)
	}
	if !state.Mode().IsRegular() || state.Mode().Perm() != 0644 {
		t.Fatalf("fixture node state must be an exposed regular file with mode 0644: %v", state.Mode())
	}
	release, err := acquire(Config{Dir: dir})
	if release != nil {
		defer release()
	}
	if err == nil {
		t.Fatal("acquire accepted existing group/other-readable node state; want rejection")
	}
}
