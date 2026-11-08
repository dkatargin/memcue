package main

import (
	"bytes"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestRepair3PreCommandLockSharesInvocation(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(dir, "claude"))
	if e := os.Mkdir(filepath.Join(dir, ".git"), 0700); e != nil {
		t.Fatal(e)
	}
	if e := os.WriteFile(filepath.Join(dir, ".git", "config"), []byte("[remote \"origin\"]\n url = https://synthetic.invalid/fixture/project.git\n"), 0600); e != nil {
		t.Fatal(e)
	}
	t.Setenv("MEMCUE_STATE_DIR", dir)
	t.Setenv("MEMCUE_FACTS", filepath.Join(dir, "no-local.db"))
	t.Setenv("MEMCUE_POSTGRES_DSN", "postgres://fixture@127.0.0.1:1/absent?sslmode=disable")
	f, e := os.OpenFile(filepath.Join(dir, "pre-command.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if e != nil {
		t.Fatal(e)
	}
	defer func() { _ = f.Close() }()
	if e = syscall.Flock(int(f.Fd()), syscall.LOCK_EX); e != nil {
		t.Fatal(e)
	}
	release := make(chan struct{})
	go func() {
		time.Sleep(4500 * time.Millisecond)
		_ = syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
		close(release)
	}()
	var out bytes.Buffer
	start := time.Now()
	_ = runPreCommand([]string{"-cwd", dir, "-session", "synthetic", "-action", "read", "--", "synthetic"}, &out)
	elapsed := time.Since(start)
	<-release
	if elapsed > 4300*time.Millisecond {
		t.Fatalf("pre-open lock escaped shared invocation deadline: %s", elapsed)
	}
}
