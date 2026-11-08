package tailnet

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestRealNodeStartsWithoutEnrolling(t *testing.T) {
	if os.Getenv("MEMCUE_TEST_TSNET_LOCAL_CONTROL") == "" {
		t.Skip("requires disposable local control plane")
	}
	cfg := Config{Dir: privateFixtureDir(t), Hostname: "memcue-unenrolled", ControlURL: os.Getenv("MEMCUE_TEST_TSNET_LOCAL_CONTROL"), Host: "database.memcue.test", Port: "5432", Timeout: 3 * time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- Run(ctx, cfg, false, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatalf("real embedded owner must start: %v", err)
	case <-time.After(10 * time.Second):
		cancel()
		<-done
		t.Fatal("real node startup was unbounded")
	}
	defer func() { cancel(); <-done }()
	status, err := request(ctx, cfg, "status")
	if err != nil || !status.Running || status.AuthURL != "" {
		t.Fatalf("safe machine status: %#v %v", status, err)
	}
	if _, err := Lookup(ctx, cfg, cfg.Host); err == nil {
		t.Fatal("unenrolled node allowed ordinary backend access")
	}
	if _, err := os.Stat(filepath.Join(cfg.Dir, "tailscaled.state")); err != nil {
		t.Fatalf("durable node state missing: %v", err)
	}
}

func TestBootstrapRetainsIdentityAfterRestart(t *testing.T) {
	control := os.Getenv("MEMCUE_TEST_TSNET_LOCAL_CONTROL")
	keyfile := os.Getenv("MEMCUE_TEST_TSNET_KEY_FILE")
	if control == "" || keyfile == "" {
		t.Skip("requires disposable Headscale and its synthetic key file")
	}
	cfg := Config{Dir: privateFixtureDir(t), Hostname: "memcue-durable", ControlURL: control, Host: "database.memcue.test", Port: "5432", KeyFile: keyfile, Timeout: 10 * time.Second}
	run := func(bootstrap bool) string {
		t.Helper()
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		ready := make(chan struct{})
		done := make(chan error, 1)
		go func() { done <- Run(ctx, cfg, bootstrap, ready) }()
		select {
		case <-ready:
		case err := <-done:
			t.Fatalf("explicit bootstrap/restart must start: %v", err)
		case <-ctx.Done():
			<-done
			t.Fatal("bootstrap exceeded deadline")
		}
		defer func() { cancel(); <-done }()
		for {
			state, err := request(ctx, cfg, "status")
			if err != nil {
				t.Fatal(err)
			}
			if state.State == "Running" {
				if state.NodeID == "" {
					t.Fatal("running status omitted durable node identity")
				}
				return state.NodeID
			}
			select {
			case <-ctx.Done():
				t.Fatalf("node did not become ready: %s", state.State)
			case <-time.After(100 * time.Millisecond):
			}
		}
	}
	first := run(true)
	cfg.KeyFile = ""
	second := run(false)
	if first != second {
		t.Fatalf("restart enrolled a different node: %s != %s", first, second)
	}
}
