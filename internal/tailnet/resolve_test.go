package tailnet

import (
	"net/netip"
	"slices"
	"tailscale.com/ipn/ipnstate"
	"tailscale.com/types/key"
	"testing"
)

func TestResolverUsesOnlyNamedTailnetPeer(t *testing.T) {
	st := &ipnstate.Status{Peer: map[key.NodePublic]*ipnstate.PeerStatus{key.NewNode().Public(): {DNSName: "database.memcue.test.", TailscaleIPs: []netip.Addr{netip.MustParseAddr("100.64.0.2"), netip.MustParseAddr("fd7a:115c:a1e0::2")}}}}
	for _, host := range []string{"database.memcue.test", "DATABASE.MEMCUE.TEST.", "database", "100.64.0.2", "fd7a:115c:a1e0::2"} {
		ips, err := resolvePeer(st, host)
		if err != nil || len(ips) == 0 {
			t.Fatalf("known peer %s must resolve without host DNS: %v %v", host, ips, err)
		}
		for _, ip := range ips {
			if !slices.Contains([]string{"100.64.0.2", "fd7a:115c:a1e0::2"}, ip) {
				t.Fatalf("unapproved result: %s", ip)
			}
		}
	}
	for _, host := range []string{"public.example", "127.0.0.1", "8.8.8.8", "100.64.0.99", "::1"} {
		if _, err := resolvePeer(st, host); err == nil {
			t.Fatalf("unapproved destination accepted: %s", host)
		}
	}
}
