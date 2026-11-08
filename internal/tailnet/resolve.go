package tailnet

import (
	"errors"
	"net/netip"
	"slices"
	"strings"
	"tailscale.com/ipn/ipnstate"
)

// resolvePeer consults the authenticated netmap only. It never invokes host DNS,
// accepts subnet routes, or treats a public address as a tailnet destination.
func resolvePeer(st *ipnstate.Status, host string) ([]string, error) {
	denied := errors.New("backend is not an unambiguous approved tailnet peer")
	if st == nil {
		return nil, denied
	}
	host = strings.ToLower(strings.TrimSuffix(host, "."))
	literal, isIP := netip.ParseAddr(host)
	var result []string
	matches := 0
	for _, peer := range st.Peer {
		name := strings.ToLower(strings.TrimSuffix(peer.DNSName, "."))
		match := name == host || (!strings.Contains(host, ".") && strings.SplitN(name, ".", 2)[0] == host)
		if isIP == nil {
			match = false
			for _, ip := range peer.TailscaleIPs {
				if ip.Unmap() == literal.Unmap() {
					match = true
				}
			}
		}
		if !match {
			continue
		}
		matches++
		for _, ip := range peer.TailscaleIPs {
			ip = ip.Unmap()
			if !netip.MustParsePrefix("100.64.0.0/10").Contains(ip) && !netip.MustParsePrefix("fd7a:115c:a1e0::/48").Contains(ip) {
				continue
			}
			if isIP == nil && ip != literal.Unmap() {
				continue
			}
			result = append(result, ip.String())
		}
	}
	if matches != 1 || len(result) == 0 {
		return nil, denied
	}
	slices.Sort(result)
	return slices.Compact(result), nil
}
