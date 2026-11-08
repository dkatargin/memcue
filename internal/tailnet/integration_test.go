package tailnet_test

import (
	"context"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/juev/memcue/internal/store"
	"github.com/juev/memcue/internal/tailnet"
	"tailscale.com/tsnet"
)

// This fixture has its own two nodes and disposable Headscale. No host VPN or live tailnet is used.
func TestIsolatedTailnetPostgresCLI(t *testing.T) {
	control, keyfile, backend, binary := os.Getenv("MEMCUE_TEST_TSNET_LOCAL_CONTROL"), os.Getenv("MEMCUE_TEST_TSNET_KEY_FILE"), os.Getenv("MEMCUE_TEST_POSTGRES_ADDR"), os.Getenv("MEMCUE_TEST_BIN")
	if control == "" || keyfile == "" || backend == "" || binary == "" {
		t.Skip("requires disposable Headscale, PostgreSQL and built CLI")
	}
	key, err := os.ReadFile(keyfile)
	if err != nil {
		t.Fatal("synthetic key unavailable")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	dbnode := &tsnet.Server{Dir: privateFixtureDir(t), Hostname: "database-memcue", ControlURL: control, AuthKey: strings.TrimSpace(string(key)), UserLogf: func(string, ...any) {}, Logf: func(string, ...any) {}}
	status, err := dbnode.Up(ctx)
	if err != nil {
		_ = dbnode.Close()
		t.Fatal("isolated database node did not become ready")
	}
	defer func() { _ = dbnode.Close() }()
	listener, err := dbnode.Listen("tcp", ":5432")
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	defer func() { cancel(); _ = listener.Close(); wg.Wait() }()
	go func() {
		for {
			c, err := listener.Accept()
			if err != nil {
				return
			}
			wg.Add(1)
			go func() {
				defer wg.Done()
				defer func() { _ = c.Close() }()
				up, err := (&net.Dialer{}).DialContext(ctx, "tcp", backend)
				if err != nil {
					return
				}
				defer func() { _ = up.Close() }()
				stop := context.AfterFunc(ctx, func() { _ = c.Close(); _ = up.Close() })
				defer stop()
				done := make(chan struct{})
				go func() { _, _ = io.Copy(up, c); _ = up.Close(); close(done) }()
				_, _ = io.Copy(c, up)
				_ = c.Close()
				_ = up.Close()
				<-done
			}()
		}
	}()
	host := strings.TrimSuffix(status.Self.DNSName, ".")
	cfg := tailnet.Config{Dir: privateFixtureDir(t), Hostname: "memcue-e2e", ControlURL: control, Host: host, Port: "5432", KeyFile: keyfile, Timeout: 10 * time.Second}
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- tailnet.Run(ctx, cfg, true, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatalf("isolated helper startup: %v", err)
	case <-ctx.Done():
		<-done
		t.Fatal("helper startup deadline")
	}
	defer func() { cancel(); <-done }()
	t.Setenv("MEMCUE_TAILSCALE_MODE", "embedded")
	t.Setenv("MEMCUE_TAILSCALE_STATE_DIR", cfg.Dir)
	t.Setenv("MEMCUE_TAILSCALE_HOSTNAME", cfg.Hostname)
	t.Setenv("MEMCUE_TAILSCALE_CONTROL_URL", control)
	t.Setenv("MEMCUE_TAILSCALE_ALLOW_LOOPBACK_CONTROL", "1")
	ips, lookupErr := tailnet.Lookup(ctx, cfg, host)
	t.Logf("isolated lookup results=%d error=%t", len(ips), lookupErr != nil)
	if lookupErr != nil || len(ips) == 0 {
		t.Fatal("isolated peer lookup failed")
	}
	probe, probeErr := tailnet.Dial(ctx, cfg, "tcp", net.JoinHostPort(ips[0], "5432"))
	if probeErr != nil {
		t.Fatal("isolated peer TCP handshake failed")
	}
	_ = probe.Close()
	dsn := (&url.URL{Scheme: "postgres", User: url.User("hermes"), Host: net.JoinHostPort(host, strconv.Itoa(5432)), Path: "/postgres", RawQuery: "sslmode=disable"}).String()
	if root := os.Getenv("MEMCUE_TEST_EMBEDDED_TLS_ROOT"); root != "" {
		u, e := url.Parse(dsn)
		if e != nil {
			t.Fatal(e)
		}
		q := u.Query()
		q.Set("sslmode", "verify-full")
		q.Set("sslrootcert", root)
		u.RawQuery = q.Encode()
		dsn = u.String()
		for _, wrong := range []string{"name", "chain"} {
			bad := *u
			if wrong == "chain" {
				q := bad.Query()
				q.Set("sslrootcert", os.Getenv("MEMCUE_TEST_EMBEDDED_WRONG_ROOT"))
				bad.RawQuery = q.Encode()
			}
			c, e := store.PostgresConfig(bad.String())
			if e != nil {
				t.Fatal(e)
			}
			if wrong == "name" {
				c.TLSConfig.ServerName = "wrong.invalid"
			}
			if e = tailnet.Configure(ctx, c); e != nil {
				t.Fatal(e)
			}
			conn, e := pgx.ConnectConfig(ctx, c)
			if e == nil {
				_ = conn.Close(ctx)
				t.Fatalf("embedded TLS %s failure accepted", wrong)
			}
			t.Logf("actual embedded PostgreSQL TLS %s rejection observed", wrong)
		}
	}
	t.Setenv("MEMCUE_POSTGRES_DSN", dsn)
	t.Setenv("MEMCUE_STATE_DIR", privateFixtureDir(t))
	t.Setenv("MEMCUE_FACTS", privateFixtureDir(t)+"/must-not-create")
	run := func(args ...string) string {
		t.Helper()
		command := exec.CommandContext(ctx, binary, args...)
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("real CLI %s failed: %v: %s", args[0], err, output)
		}
		return string(output)
	}
	run("add", "-scope", "repo:tailnetfixture", "--", "Synthetic larch PROJ-681 is stored through the isolated tailnet")
	output := run("search", "-json", "-in", "repo:tailnetfixture", "larch PROJ-681")
	if !strings.Contains(output, "Synthetic larch PROJ-681") {
		t.Fatalf("tailnet CLI search omitted synthetic write: %s", output)
	}
	if _, err := os.Stat(os.Getenv("MEMCUE_FACTS")); !os.IsNotExist(err) {
		t.Fatal("remote operation created a local fact base")
	}
	// Two real subprocess clients share this owner and the actual database route.
	concurrent := make(chan error, 2)
	for i := 0; i < 2; i++ {
		go func() {
			cmd := exec.CommandContext(ctx, binary, "search", "-json", "-in", "repo:tailnetfixture", "larch PROJ-681")
			out, e := cmd.CombinedOutput()
			if e == nil && !strings.Contains(string(out), "Synthetic larch PROJ-681") {
				e = fmt.Errorf("concurrent remote snapshot omitted fixture")
			}
			concurrent <- e
		}()
	}
	for i := 0; i < 2; i++ {
		if e := <-concurrent; e != nil {
			t.Fatal(e)
		}
	}
	t.Log("two concurrent native CLI searches shared the embedded owner successfully")
	// Supplemental model-free adapter invocations retain the same real remote environment.
	repairRealCancel(t, ctx, dsn)
	if driver := os.Getenv("MEMCUE_TEST_REMOTE_HERMES"); driver != "" {
		command := exec.CommandContext(ctx, "python3", "-I", "-B", driver)
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("Hermes remote adapter: %v %s", err, output)
		}
		t.Log(string(output))
	}
	if driver := os.Getenv("MEMCUE_TEST_REMOTE_DSH"); driver != "" {
		command := exec.CommandContext(ctx, os.Getenv("MEMCUE_TEST_NODE"), driver)
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("DSH remote adapter: %v %s", err, output)
		}
		t.Log(string(output))
	}

}

func TestRepairIsolatedTailnetIPv6CLI(t *testing.T) {
	control, keyfile, backend, binary := os.Getenv("MEMCUE_TEST_TSNET_LOCAL_CONTROL"), os.Getenv("MEMCUE_TEST_TSNET_KEY_FILE"), os.Getenv("MEMCUE_TEST_POSTGRES_ADDR"), os.Getenv("MEMCUE_TEST_BIN")
	if control == "" || keyfile == "" || backend == "" || binary == "" {
		t.Skip("requires disposable Headscale, PostgreSQL and built CLI")
	}
	key, err := os.ReadFile(keyfile)
	if err != nil {
		t.Fatal("synthetic key unavailable")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	dbnode := &tsnet.Server{Dir: privateFixtureDir(t), Hostname: "database-memcue-v6", ControlURL: control, AuthKey: strings.TrimSpace(string(key)), UserLogf: func(string, ...any) {}, Logf: func(string, ...any) {}}
	status, err := dbnode.Up(ctx)
	if err != nil {
		_ = dbnode.Close()
		t.Fatal("isolated database node did not become ready")
	}
	defer func() { _ = dbnode.Close() }()
	listener, err := dbnode.Listen("tcp", ":5432")
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	defer func() { cancel(); _ = listener.Close(); wg.Wait() }()
	go func() {
		for {
			c, err := listener.Accept()
			if err != nil {
				return
			}
			wg.Add(1)
			go func() {
				defer wg.Done()
				defer func() { _ = c.Close() }()
				up, err := (&net.Dialer{}).DialContext(ctx, "tcp", backend)
				if err != nil {
					return
				}
				defer func() { _ = up.Close() }()
				stop := context.AfterFunc(ctx, func() { _ = c.Close(); _ = up.Close() })
				defer stop()
				done := make(chan struct{})
				go func() { _, _ = io.Copy(up, c); _ = up.Close(); close(done) }()
				_, _ = io.Copy(c, up)
				_ = c.Close()
				_ = up.Close()
				<-done
			}()
		}
	}()
	host := ""
	for _, ip := range status.TailscaleIPs {
		if ip.Is6() {
			host = ip.String()
		}
	}
	if host == "" {
		t.Fatal("isolated control plane supplied no IPv6 address")
	}
	cfg := tailnet.Config{Dir: privateFixtureDir(t), Hostname: "memcue-e2e-v6", ControlURL: control, Host: host, Port: "5432", KeyFile: keyfile, Timeout: 10 * time.Second}
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- tailnet.Run(ctx, cfg, true, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatalf("isolated helper startup: %v", err)
	case <-ctx.Done():
		<-done
		t.Fatal("helper startup deadline")
	}
	defer func() { cancel(); <-done }()
	t.Setenv("MEMCUE_TAILSCALE_MODE", "embedded")
	t.Setenv("MEMCUE_TAILSCALE_STATE_DIR", cfg.Dir)
	t.Setenv("MEMCUE_TAILSCALE_HOSTNAME", cfg.Hostname)
	t.Setenv("MEMCUE_TAILSCALE_CONTROL_URL", control)
	t.Setenv("MEMCUE_TAILSCALE_ALLOW_LOOPBACK_CONTROL", "1")
	ips, lookupErr := tailnet.Lookup(ctx, cfg, host)
	t.Logf("isolated lookup results=%d error=%t", len(ips), lookupErr != nil)
	if lookupErr != nil || len(ips) == 0 {
		t.Fatal("isolated peer lookup failed")
	}
	probe, probeErr := tailnet.Dial(ctx, cfg, "tcp", net.JoinHostPort(ips[0], "5432"))
	if probeErr != nil {
		t.Fatal("isolated peer TCP handshake failed")
	}
	_ = probe.Close()
	dsn := (&url.URL{Scheme: "postgres", User: url.User("hermes"), Host: net.JoinHostPort(host, strconv.Itoa(5432)), Path: "/postgres", RawQuery: "sslmode=disable"}).String()
	t.Setenv("MEMCUE_POSTGRES_DSN", dsn)
	t.Setenv("MEMCUE_STATE_DIR", privateFixtureDir(t))
	t.Setenv("MEMCUE_FACTS", privateFixtureDir(t)+"/must-not-create")
	run := func(args ...string) string {
		t.Helper()
		command := exec.CommandContext(ctx, binary, args...)
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("real CLI %s failed: %v: %s", args[0], err, output)
		}
		return string(output)
	}
	run("add", "-scope", "repo:tailnetfixture", "--", "Synthetic larch PROJ-681 is stored through the isolated tailnet")
	output := run("search", "-json", "-in", "repo:tailnetfixture", "larch PROJ-681")
	if !strings.Contains(output, "Synthetic larch PROJ-681") {
		t.Fatalf("tailnet CLI search omitted synthetic write: %s", output)
	}
	if _, err := os.Stat(os.Getenv("MEMCUE_FACTS")); !os.IsNotExist(err) {
		t.Fatal("remote operation created a local fact base")
	}
	// Supplemental model-free adapter invocations retain the same real remote environment.
	repairRealCancel(t, ctx, dsn)
	if driver := os.Getenv("MEMCUE_TEST_REMOTE_HERMES"); driver != "" {
		command := exec.CommandContext(ctx, "python3", "-I", "-B", driver)
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("Hermes remote adapter: %v %s", err, output)
		}
		t.Log(string(output))
	}
	if driver := os.Getenv("MEMCUE_TEST_REMOTE_DSH"); driver != "" {
		command := exec.CommandContext(ctx, os.Getenv("MEMCUE_TEST_NODE"), driver)
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("DSH remote adapter: %v %s", err, output)
		}
		t.Log(string(output))
	}

}
