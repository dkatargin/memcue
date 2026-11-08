package tailnet

import (
	"context"
	"errors"
	"net"
	"strconv"
	"time"
)

func Lookup(ctx context.Context, c Config, host string) ([]string, error) {
	if err := checkProfile(c); err != nil {
		return nil, err
	}
	conn, r, err := exchange(ctx, c, message{Version: 1, Op: "lookup", Host: host})
	if err != nil {
		return nil, err
	}
	_ = conn.Close()
	return r.IPs, nil
}
func Dial(ctx context.Context, c Config, network, address string) (net.Conn, error) {
	if err := checkProfile(c); err != nil {
		return nil, err
	}
	if network != "tcp" {
		return nil, errors.New("embedded transport only supports PostgreSQL TCP")
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return nil, errors.New("invalid backend address")
	}
	conn, _, err := exchange(ctx, c, message{Version: 1, Op: "dial", Host: host, Port: port})
	if err != nil {
		return nil, err
	}
	_ = conn.SetDeadline(time.Time{})
	return &tcpPeerConn{Conn: conn, peer: &net.TCPAddr{IP: net.ParseIP(host), Port: mustPort(port)}}, nil
}

type tcpPeerConn struct {
	net.Conn
	peer *net.TCPAddr
}

func (c *tcpPeerConn) RemoteAddr() net.Addr { return c.peer }
func mustPort(port string) int              { n, _ := strconv.Atoi(port); return n }
