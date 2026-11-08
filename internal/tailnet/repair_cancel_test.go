package tailnet

import (
	"context"
	"errors"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgproto3"
	"net"
	"testing"
	"time"
)

type cancelRepairNode struct {
	fixtureNode
	cancelled chan struct{}
}

func (n *cancelRepairNode) Dial(context.Context, string) (net.Conn, error) {
	a, b := net.Pipe()
	go func() {
		defer func() { _ = b.Close() }()
		be := pgproto3.NewBackend(b, b)
		msg, err := be.ReceiveStartupMessage()
		if err != nil {
			return
		}
		if _, ok := msg.(*pgproto3.CancelRequest); ok {
			close(n.cancelled)
			return
		}
		be.Send(&pgproto3.AuthenticationOk{})
		be.Send(&pgproto3.BackendKeyData{ProcessID: 123, SecretKey: []byte{0, 0, 1, 200}})
		be.Send(&pgproto3.ReadyForQuery{TxStatus: 'I'})
		if be.Flush() != nil {
			return
		}
		for {
			if _, err := be.Receive(); err != nil {
				return
			}
		}
	}()
	return a, nil
}
func TestRepairPGCancelDelivered(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	n := &cancelRepairNode{cancelled: make(chan struct{})}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, n, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	}
	defer func() { cancel(); <-done }()
	cfg, err := pgconn.ParseConfig("postgres://fixture@database.memcue.test:5432/fixture?sslmode=disable&passfile=/dev/null")
	if err != nil {
		t.Fatal(err)
	}
	cfg.LookupFunc = func(ctx context.Context, h string) ([]string, error) { return Lookup(ctx, c, h) }
	cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
		return Dial(ctx, c, network, address)
	}
	pg, err := pgconn.ConnectConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = pg.Close(ctx) }()
	if err := pg.CancelRequest(ctx); err != nil {
		t.Fatalf("real pgconn cancellation must reach selected TCP peer: %v", err)
	}
	select {
	case <-n.cancelled:
	case <-ctx.Done():
		t.Fatal("cancel packet not delivered")
	}
}

type routedCancelRepairNode struct {
	cancelRepairNode
	ips   []string
	calls chan string
	fail  string
}

func (n *routedCancelRepairNode) Lookup(context.Context, string) ([]string, error) { return n.ips, nil }
func (n *routedCancelRepairNode) Dial(ctx context.Context, a string) (net.Conn, error) {
	n.calls <- a
	if a == n.fail {
		return nil, errors.New("synthetic first-address outage")
	}
	return n.cancelRepairNode.Dial(ctx, a)
}
func TestRepairCancelPeerAddressMatrix(t *testing.T) {
	for _, tc := range []struct {
		name, host string
		ips        []string
		fail       string
	}{{"DNS-v4", "database.memcue.test", []string{"100.64.0.2"}, ""}, {"IP-v4", "100.64.0.2", []string{"100.64.0.2"}, ""}, {"DNS-v6", "database.memcue.test", []string{"fd7a:115c:a1e0::2"}, ""}, {"IP-v6", "fd7a:115c:a1e0::2", []string{"fd7a:115c:a1e0::2"}, ""}, {"multiple", "database.memcue.test", []string{"100.64.0.2", "fd7a:115c:a1e0::2"}, "100.64.0.2:5432"}} {
		t.Run(tc.name, func(t *testing.T) {
			c := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: tc.host, Port: "5432", Timeout: time.Second}
			n := &routedCancelRepairNode{cancelRepairNode: cancelRepairNode{cancelled: make(chan struct{})}, ips: tc.ips, calls: make(chan string, 8), fail: tc.fail}
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			ready := make(chan struct{})
			done := make(chan error, 1)
			go func() { done <- serve(ctx, c, n, ready) }()
			select {
			case <-ready:
			case err := <-done:
				t.Fatal(err)
			}
			defer func() { cancel(); <-done }()
			cfg, err := pgconn.ParseConfig("postgres://fixture@" + net.JoinHostPort(tc.host, "5432") + "/fixture?sslmode=disable&passfile=/dev/null")
			if err != nil {
				t.Fatal(err)
			}
			cfg.LookupFunc = func(ctx context.Context, h string) ([]string, error) { return Lookup(ctx, c, h) }
			cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
				return Dial(ctx, c, network, address)
			}
			pg, err := pgconn.ConnectConfig(ctx, cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = pg.Close(ctx) }()
			selected := pg.Conn().RemoteAddr().String()
			if pg.Conn().RemoteAddr().Network() != "tcp" {
				t.Fatal("IPC address escaped tunnel")
			}
			if err := pg.CancelRequest(ctx); err != nil {
				t.Fatal(err)
			}
			select {
			case <-n.cancelled:
			case <-ctx.Done():
				t.Fatal("actual cancel packet absent")
			}
			last := ""
			for len(n.calls) > 0 {
				last = <-n.calls
			}
			if last != selected {
				t.Fatalf("cancel dialed %s instead of selected %s", last, selected)
			}
		})
	}
}

func TestRepairPGAsyncCleanupDeliversCancel(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Hostname: "fixture", Host: "database.memcue.test", Port: "5432", Timeout: time.Second}
	n := &cancelRepairNode{cancelled: make(chan struct{})}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	ready := make(chan struct{})
	done := make(chan error, 1)
	go func() { done <- serve(ctx, c, n, ready) }()
	select {
	case <-ready:
	case err := <-done:
		t.Fatal(err)
	}
	defer func() { cancel(); <-done }()
	cfg, err := pgconn.ParseConfig("postgres://fixture@database.memcue.test:5432/fixture?sslmode=disable&passfile=/dev/null")
	if err != nil {
		t.Fatal(err)
	}
	cfg.LookupFunc = func(ctx context.Context, h string) ([]string, error) { return Lookup(ctx, c, h) }
	cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
		return Dial(ctx, c, network, address)
	}
	pg, err := pgconn.ConnectConfig(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = pg.Close(ctx) }()
	query, stop := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer stop()
	if _, err := pg.Exec(query, "select 1").ReadAll(); err == nil {
		t.Fatal("unanswered synthetic query unexpectedly succeeded")
	}
	select {
	case <-n.cancelled:
	case <-ctx.Done():
		t.Fatal("pgconn async cleanup failed to deliver actual CancelRequest")
	}
	select {
	case <-pg.CleanupDone():
	case <-ctx.Done():
		t.Fatal("pgconn async cleanup did not finish")
	}
}
