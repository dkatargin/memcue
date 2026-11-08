package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRepair2BatchPreflightBeforeBackend(t *testing.T) {
	for _, remote := range []bool{false, true} {
		for _, body := range []string{`[{"Content":"  "}]`, `null`, `[{}]`} {
			t.Run(body+map[bool]string{false: "local", true: "remote"}[remote], func(t *testing.T) {
				dir := t.TempDir()
				base := filepath.Join(dir, "absent.db")
				input := filepath.Join(dir, "batch.json")
				t.Setenv("MEMCUE_FACTS", base)
				t.Setenv("MEMCUE_POSTGRES_DSN", "")
				if remote {
					t.Setenv("MEMCUE_POSTGRES_DSN", "postgres://fixture@127.0.0.1:1/absent?sslmode=disable")
				}
				if err := os.WriteFile(input, []byte(body), 0600); err != nil {
					t.Fatal(err)
				}
				var out bytes.Buffer
				err := runAdd([]string{"-batch", input}, &out)
				if _, stat := os.Stat(base); !os.IsNotExist(stat) {
					t.Errorf("invalid batch created local base: %v", stat)
				}
				if err == nil || !strings.Contains(err.Error(), "empty fact") && !strings.Contains(err.Error(), "JSON array") {
					t.Fatalf("preflight must win over backend access: %v", err)
				}
			})
		}
	}
}
