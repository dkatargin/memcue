package main

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestConnectStatusOffDoesNotCreateIdentity(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "identity")
	t.Setenv("MEMCUE_TAILSCALE_MODE", "off")
	t.Setenv("MEMCUE_TAILSCALE_STATE_DIR", dir)
	var out bytes.Buffer
	if err := runConnect([]string{"status"}, &out); err != nil {
		t.Fatalf("status must work without enrollment: %v", err)
	}
	var got map[string]any
	if err := json.Unmarshal(out.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	if got["mode"] != "off" || got["running"] != false {
		t.Fatalf("unexpected status: %s", out.String())
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Fatalf("status created identity: %v", err)
	}
}

func TestConnectStatusRejectsUnknownMode(t *testing.T) {
	t.Setenv("MEMCUE_TAILSCALE_MODE", "embeddde-secret")
	var out bytes.Buffer
	err := runConnect([]string{"status"}, &out)
	if err == nil {
		t.Fatal("unknown transport mode accepted")
	}
	if bytes.Contains([]byte(err.Error()), []byte("embeddde-secret")) {
		t.Fatal("configuration value leaked")
	}
}
