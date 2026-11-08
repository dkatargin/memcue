package tailnet

import (
	"bufio"
	"context"
	"io"
	"net"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

type fixtureNode struct {
	status State
	logins atomic.Int32
}

func (n *fixtureNode) Status(context.Context) (State, error) {
	if n.status.State != "" {
		return n.status, nil
	}
	return State{Running: true, State: "Running"}, nil
}
func (n *fixtureNode) Login(context.Context) error { n.logins.Add(1); return nil }
func (*fixtureNode) Dial(context.Context, string) (net.Conn, error) {
	a, b := net.Pipe()
	go func() { defer func() { _ = b.Close() }(); _, _ = io.Copy(b, b) }()
	return a, nil
}
func (*fixtureNode) Lookup(context.Context, string) ([]string, error) {
	return []string{"100.64.0.2"}, nil
}
func (*fixtureNode) Close() error { return nil }

func TestHelperSharesNodeAcrossClients(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg, &fixtureNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatalf("persistent owner must serve clients: %v", err)
	case <-time.After(3 * time.Second):
		t.Fatal("helper failed to start")
	}
	for range 3 {
		s, err := request(ctx, cfg, "status")
		if err != nil || !s.Running || s.State != "Running" {
			t.Fatalf("shared status: %#v %v", s, err)
		}
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("helper did not stop")
	}
}

func TestHelperRejectsPublicIdentityDirectory(t *testing.T) {
	dir := privateFixtureDir(t)
	if err := os.Chmod(dir, 0755); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, Config{Dir: dir}, &fixtureNode{}, ready) }()
	select {
	case <-ready:
		cancel()
		<-done
		t.Fatal("helper accepted an identity directory readable by other users")
	case err := <-done:
		if err == nil {
			t.Fatal("unsafe state accepted")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("permission validation blocked")
	}
}

func TestIdentityOwnershipSurvivesMissingSocket(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg, &fixtureNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	case <-time.After(3 * time.Second):
		t.Fatal("first owner did not start")
	}
	defer func() { cancel(); <-done }()
	if err := os.Remove(filepath.Join(cfg.Dir, "helper.sock")); err != nil {
		t.Fatal(err)
	}
	secondCtx, stop := context.WithCancel(context.Background())
	defer stop()
	secondReady := make(chan struct{})
	secondDone := make(chan error, 1)
	go func() { secondDone <- serve(secondCtx, cfg, &fixtureNode{}, secondReady) }()
	select {
	case <-secondReady:
		stop()
		<-secondDone
		t.Fatal("second process may own the same durable identity when socket disappears")
	case err := <-secondDone:
		if err == nil {
			t.Fatal("second owner accepted")
		}
	case <-time.After(3 * time.Second):
		t.Fatal("ownership contention must fail boundedly")
	}
}

func TestIdentityCannotSwitchControlServer(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Hostname: "fixture", ControlURL: "https://first.invalid", Host: "database.memcue.test", Port: "5432"}
	release, err := acquire(cfg)
	if err != nil {
		t.Fatal(err)
	}
	release()
	cfg.ControlURL = "https://second.invalid"
	release, err = acquire(cfg)
	if err == nil {
		release()
		t.Fatal("existing identity silently changed tailnets")
	}
}

func TestClientsUseOnlyConfiguredBackend(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg, &fixtureNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	case <-time.After(3 * time.Second):
		t.Fatal("owner did not start")
	}
	defer func() { cancel(); <-done }()
	ips, err := Lookup(ctx, cfg, cfg.Host)
	if err != nil || len(ips) != 1 || ips[0] != "100.64.0.2" {
		t.Fatalf("backend lookup must use owner: %v %v", ips, err)
	}
	conn, err := Dial(ctx, cfg, "tcp", "100.64.0.2:5432")
	if err != nil {
		t.Fatalf("backend connection must use owner: %v", err)
	}
	defer func() { _ = conn.Close() }()
	_ = conn.SetDeadline(time.Now().Add(time.Second))
	if _, err = conn.Write([]byte("synthetic")); err != nil {
		t.Fatal(err)
	}
	got := make([]byte, 9)
	if _, err = io.ReadFull(conn, got); err != nil || string(got) != "synthetic" {
		t.Fatalf("tunnel bytes: %q %v", got, err)
	}
	if _, err = Dial(ctx, cfg, "tcp", "127.0.0.1:5432"); err == nil {
		t.Fatal("helper became an arbitrary proxy")
	}
	if _, err = Lookup(ctx, cfg, "public.example"); err == nil {
		t.Fatal("unconfigured DNS destination accepted")
	}
}

func TestOnlyExplicitLoginDisclosesAuthorizationURL(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Timeout: time.Second}
	n := &fixtureNode{status: State{Running: true, State: "NeedsLogin", AuthURL: "https://login.invalid/synthetic-secret"}}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg, n, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	case <-time.After(3 * time.Second):
		t.Fatal("owner did not start")
	}
	defer func() { cancel(); <-done }()
	status, err := request(ctx, cfg, "status")
	if err != nil || status.AuthURL != "" || n.logins.Load() != 0 {
		t.Fatalf("ordinary status enrolled or leaked URL: %#v %v", status, err)
	}
	login, err := request(ctx, cfg, "login")
	if err != nil || login.AuthURL != n.status.AuthURL || n.logins.Load() != 1 {
		t.Fatalf("explicit login must expose browser flow: %#v %v", login, err)
	}
}

func TestOffStopsOwnerAndPreservesIdentity(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, cfg, &fixtureNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	case <-time.After(3 * time.Second):
		t.Fatal("owner did not start")
	}
	_, err := request(ctx, cfg, "off")
	if err != nil {
		cancel()
		<-done
		t.Fatalf("off must stop helper without logout: %v", err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(3 * time.Second):
		cancel()
		<-done
		t.Fatal("off did not stop helper")
	}
	if _, err := os.Stat(filepath.Join(cfg.Dir, "profile.json")); err != nil {
		t.Fatal("off destroyed durable profile")
	}
	release, err := acquire(cfg)
	if err != nil {
		t.Fatal("off retained ownership lock")
	}
	release()
}

func TestClientRejectsUntrustedIPC(t *testing.T) {
	cfg := Config{Dir: privateFixtureDir(t), Timeout: time.Second}
	if err := os.Chmod(cfg.Dir, 0755); err != nil {
		t.Fatal(err)
	}
	path, closeDir, err := socketPath(cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer closeDir()
	l, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	defer func() { _ = l.Close(); <-done }()
	go func() {
		defer close(done)
		conn, err := l.Accept()
		if err != nil {
			return
		}
		defer func() { _ = conn.Close() }()
		_, _ = bufio.NewReader(conn).ReadString('\n')
		_, _ = conn.Write([]byte("{\"running\":true,\"state\":\"Running\"}\n"))
	}()
	if _, err := request(context.Background(), cfg, "status"); err == nil {
		t.Fatal("client accepted IPC from a directory accessible to other users")
	}
}
