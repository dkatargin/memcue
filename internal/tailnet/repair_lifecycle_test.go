package tailnet

import (
	"context"
	"errors"
	"net"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

type unhealthyRepairNode struct{ fixtureNode }

func (*unhealthyRepairNode) Status(context.Context) (State, error) {
	return State{}, errors.New("synthetic status failure")
}
func TestRepairOffIndependentOfStatus(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, &unhealthyRepairNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	}
	_, err := Admin(ctx, c, "off")
	if err != nil {
		cancel()
		<-done
		t.Fatalf("authenticated off must ignore status failure: %v", err)
	}
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(time.Second):
		cancel()
		<-done
		t.Fatal("off failed to release owner")
	}
	release, err := acquire(c)
	if err != nil {
		t.Fatal(err)
	}
	release()
}

type closingRepairNode struct {
	fixtureNode
	closes int
}

func (n *closingRepairNode) Close() error { n.closes++; return nil }
func TestRepairIPCSetupClosesNode(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t)}
	if err := os.WriteFile(filepath.Join(c.Dir, "helper.sock"), []byte("fixture"), 0600); err != nil {
		t.Fatal(err)
	}
	n := &closingRepairNode{}
	err := serve(context.Background(), c, n, make(chan struct{}))
	if err == nil {
		t.Fatal("non-socket IPC accepted")
	}
	if n.closes != 1 {
		t.Fatalf("node closes=%d, want exactly one before releasing ownership", n.closes)
	}
	release, err := acquire(c)
	if err != nil {
		t.Fatal(err)
	}
	release()
}

type blockedStatusRepairNode struct {
	fixtureNode
	calls atomic.Int32
}

func (n *blockedStatusRepairNode) Status(ctx context.Context) (State, error) {
	n.calls.Add(1)
	<-ctx.Done()
	return State{}, ctx.Err()
}
func TestRepairOffNeverWaitsForStatus(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Timeout: time.Second}
	n := &blockedStatusRepairNode{}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, n, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	}
	state, err := Admin(ctx, c, "off")
	if err != nil {
		cancel()
		<-done
		t.Fatal(err)
	}
	if state.State != "Stopping" {
		t.Fatalf("ack must report asynchronous stopping: %#v", state)
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		cancel()
		<-done
		t.Fatal("off blocked")
	}
	if n.calls.Load() != 0 {
		t.Fatal("off called status")
	}
}

type trackedRepairConn struct {
	net.Conn
	once   sync.Once
	active *atomic.Int32
}

func (c *trackedRepairConn) Close() error {
	c.once.Do(func() { c.active.Add(-1) })
	return c.Conn.Close()
}

type activeRepairNode struct {
	fixtureNode
	active   atomic.Int32
	badOrder atomic.Bool
	closes   atomic.Int32
}

func (n *activeRepairNode) Dial(ctx context.Context, a string) (net.Conn, error) {
	c, err := n.fixtureNode.Dial(ctx, a)
	if err != nil {
		return nil, err
	}
	n.active.Add(1)
	return &trackedRepairConn{Conn: c, active: &n.active}, nil
}
func (n *activeRepairNode) Close() error {
	if n.active.Load() != 0 {
		n.badOrder.Store(true)
	}
	n.closes.Add(1)
	return nil
}
func TestRepairOffClosesConcurrentStreamsBeforeNode(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	n := &activeRepairNode{}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, n, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	}
	var streams []net.Conn
	for range 2 {
		conn, err := Dial(ctx, c, "tcp", "100.64.0.2:5432")
		if err != nil {
			cancel()
			<-done
			t.Fatal(err)
		}
		streams = append(streams, conn)
	}
	defer func() {
		for _, c := range streams {
			_ = c.Close()
		}
	}()
	if _, err := Admin(ctx, c, "off"); err != nil {
		cancel()
		<-done
		t.Fatal(err)
	}
	select {
	case <-done:
	case <-time.After(2 * time.Second):
		cancel()
		<-done
		t.Fatal("active streams blocked shutdown")
	}
	if n.badOrder.Load() || n.closes.Load() != 1 {
		t.Fatalf("cleanup order/count: bad=%t closes=%d", n.badOrder.Load(), n.closes.Load())
	}
	release, err := acquire(c)
	if err != nil {
		t.Fatal(err)
	}
	release()
}

type lockOrderRepairNode struct {
	fixtureNode
	c             Config
	releasedEarly bool
	closes        int
}

func (n *lockOrderRepairNode) Close() error {
	n.closes++
	release, err := acquire(n.c)
	if err == nil {
		n.releasedEarly = true
		release()
	}
	return nil
}
func TestRepairIPCFailureClosesBeforeLockRelease(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t)}
	if err := os.WriteFile(filepath.Join(c.Dir, "helper.sock"), []byte("synthetic"), 0600); err != nil {
		t.Fatal(err)
	}
	n := &lockOrderRepairNode{c: c}
	if err := serve(context.Background(), c, n, make(chan struct{})); err == nil {
		t.Fatal("non-socket accepted")
	}
	if n.releasedEarly || n.closes != 1 {
		t.Fatalf("ownership order: early=%t closes=%d", n.releasedEarly, n.closes)
	}
	release, err := acquire(c)
	if err != nil {
		t.Fatal(err)
	}
	release()
}

func TestRepairOffInterruptsIdleHandshake(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Timeout: time.Second}
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, &fixtureNode{}, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	}
	path, closeDir, err := socketPath(c)
	if err != nil {
		t.Fatal(err)
	}
	defer closeDir()
	idle, err := net.Dial("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = idle.Close() }()
	// A completed status roundtrip gives the accept loop opportunity to admit the idle connection.
	if _, err := Admin(ctx, c, "status"); err != nil {
		t.Fatal(err)
	}
	if _, err := Admin(ctx, c, "off"); err != nil {
		cancel()
		<-done
		t.Fatal(err)
	}
	select {
	case <-done:
	case <-time.After(200 * time.Millisecond):
		_ = idle.Close()
		cancel()
		<-done
		t.Fatal("idle handshake delayed authenticated shutdown")
	}
}
