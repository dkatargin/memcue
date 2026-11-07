package main

import (
	"bytes"
	"errors"
	"flag"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestDreamHelpDescribesOnlyCurrentWork(t *testing.T) {
	path := filepath.Join(t.TempDir(), "help.txt")
	f, err := os.Create(path)
	if err != nil {
		t.Fatal(err)
	}
	prior := os.Stderr
	os.Stderr = f
	err = runDream([]string{"-h"}, &bytes.Buffer{})
	os.Stderr = prior
	if e := f.Close(); e != nil {
		t.Fatal(e)
	}
	if !errors.Is(err, flag.ErrHelp) {
		t.Fatalf("help failed: %v", err)
	}
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(b), "query,") {
		t.Fatal("dream help still advertises removed query work")
	}
	if !strings.Contains(string(b), "split") || !strings.Contains(string(b), "scope") {
		t.Fatal("help lost current maintenance tasks")
	}
}
