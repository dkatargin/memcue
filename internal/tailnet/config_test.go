package tailnet

import (
	"context"
	"github.com/jackc/pgx/v5"
	"strings"
	"testing"
	"time"
)

func TestAmbientTailnetCredentialsAreRejected(t *testing.T) {
	t.Setenv("TS_AUTHKEY", "synthetic-credential-do-not-print")
	t.Setenv("MEMCUE_TAILSCALE_STATE_DIR", privateFixtureDir(t)+"/missing")
	_, err := Settings("database.memcue.test", "5432")
	if err == nil {
		t.Fatal("inherited TS_AUTHKEY may silently enroll helper")
	}
	if strings.Contains(err.Error(), "synthetic-credential") {
		t.Fatal("ambient credential leaked")
	}
}

func TestConfiguredClientCannotReuseDifferentTailnet(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Hostname: "fixture", ControlURL: "https://first.invalid", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, &fixtureNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	case <-time.After(3 * time.Second):
		t.Fatal("helper did not start")
	}
	defer func() { cancel(); <-done }()
	t.Setenv("MEMCUE_TAILSCALE_MODE", "embedded")
	t.Setenv("MEMCUE_TAILSCALE_STATE_DIR", c.Dir)
	t.Setenv("MEMCUE_TAILSCALE_HOSTNAME", c.Hostname)
	t.Setenv("MEMCUE_TAILSCALE_CONTROL_URL", "https://second.invalid")
	pg := &pgx.ConnConfig{}
	pg.Host = c.Host
	pg.Port = 5432
	if err := Configure(ctx, pg); err == nil {
		t.Fatal("client used a helper from a different configured control server")
	}
}
