package store

import (
	"context"
	"io"
	"net"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
)

// Exercise pgconn's real packet write and response wait, not a model of its dialer.
func TestRepair2AllocatedCancellationSocketLifetime(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_DSN")
	if dsn == "" {
		t.Skip("isolated PostgreSQL required")
	}
	for _, response := range []bool{false, true} {
		t.Run(map[bool]string{false: "packet-write", true: "response-read"}[response], func(t *testing.T) {
			cfg, err := PostgresConfig(dsn)
			if err != nil {
				t.Fatal(err)
			}
			dial := cfg.DialFunc
			var calls atomic.Int32
			peers := make(chan net.Conn, 1)
			cfg.DialFunc = func(ctx context.Context, n, a string) (net.Conn, error) {
				if calls.Add(1) == 1 {
					return dial(ctx, n, a)
				}
				x, y := net.Pipe()
				peers <- y
				return x, nil
			}
			op, cancel := context.WithTimeout(context.Background(), time.Second)
			defer cancel()
			c, err := pgx.ConnectConfig(op, budgetConfig(op, cfg))
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = c.PgConn().Conn().Close() }()
			finished := make(chan error, 1)
			go func() { finished <- c.PgConn().CancelRequest(context.Background()) }()
			var peer net.Conn
			select {
			case peer = <-peers:
			case <-time.After(time.Second):
				t.Fatal("actual CancelRequest dial missing")
			}
			defer func() { _ = peer.Close() }()
			if response {
				packet := make([]byte, 16)
				if _, err = io.ReadFull(peer, packet); err != nil {
					t.Fatal(err)
				}
			}
			cancel()
			completed := false
			select {
			case <-finished:
				completed = true
			case <-time.After(100 * time.Millisecond):
			}
			if !completed {
				t.Error("allocated cancellation socket kept CancelRequest blocked after owner cancellation")
			}
			_ = peer.SetWriteDeadline(time.Now().Add(30 * time.Millisecond))
			_, err = peer.Write([]byte{1})
			if ne, ok := err.(net.Error); err == nil || ok && ne.Timeout() {
				t.Errorf("allocated cancellation peer remains open: %v", err)
			}

			_ = peer.Close()
			if !completed {
				select {
				case <-finished:
				case <-time.After(time.Second):
					t.Fatal("cancel request goroutine survived stream cleanup")
				}
			}
		})
	}
}
