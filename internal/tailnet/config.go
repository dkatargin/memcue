package tailnet

import (
	"context"
	"errors"
	"net"
	"net/netip"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
)

func Mode() (string, error) {
	mode := os.Getenv("MEMCUE_TAILSCALE_MODE")
	if mode == "" {
		mode = "off"
	}
	if mode != "off" && mode != "embedded" {
		return "", errors.New("MEMCUE_TAILSCALE_MODE must be off or embedded")
	}
	return mode, nil
}
func StateDir() (string, error) {
	dir := os.Getenv("MEMCUE_TAILSCALE_STATE_DIR")
	if dir == "" {
		base, err := os.UserConfigDir()
		if err != nil {
			return "", errHelper
		}
		dir = filepath.Join(base, "memcue", "tailnet")
	}
	if !filepath.IsAbs(dir) {
		return "", errors.New("MEMCUE_TAILSCALE_STATE_DIR must be absolute")
	}
	return filepath.Clean(dir), nil
}
func rejectAmbient() error {
	for _, entry := range os.Environ() {
		name, value, _ := strings.Cut(entry, "=")
		if strings.HasPrefix(name, "TS_") && (name != "TS_NO_LOGS_NO_SUPPORT" || value != "true") {
			return errors.New("ambient TS_* variables are not supported; unset them and use explicit MEMCUE_TAILSCALE settings")
		}
	}
	return nil
}
func Settings(host, port string) (Config, error) {
	if err := rejectAmbient(); err != nil {
		return Config{}, err
	}
	dir, err := StateDir()
	if err != nil {
		return Config{}, err
	}
	c := Config{Dir: dir, Host: host, Port: port, Hostname: os.Getenv("MEMCUE_TAILSCALE_HOSTNAME"), ControlURL: os.Getenv("MEMCUE_TAILSCALE_CONTROL_URL"), KeyFile: os.Getenv("MEMCUE_TAILSCALE_AUTH_KEY_FILE"), Timeout: 5 * time.Second}
	if c.Hostname == "" {
		c.Hostname = "memcue"
	}
	if c.ControlURL == "" {
		c.ControlURL = "https://controlplane.tailscale.com"
	}
	if !regexp.MustCompile(`^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$`).MatchString(c.Hostname) {
		return Config{}, errors.New("invalid MEMCUE_TAILSCALE_HOSTNAME")
	}
	u, err := url.Parse(c.ControlURL)
	if err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return Config{}, errors.New("invalid tailnet control URL")
	}
	if u.Scheme != "https" {
		ip, e := netip.ParseAddr(u.Hostname())
		if u.Scheme != "http" || e != nil || !ip.IsLoopback() || os.Getenv("MEMCUE_TAILSCALE_ALLOW_LOOPBACK_CONTROL") != "1" {
			return Config{}, errors.New("tailnet control URL requires HTTPS; isolated loopback fixtures require MEMCUE_TAILSCALE_ALLOW_LOOPBACK_CONTROL=1")
		}
	}
	if value := os.Getenv("MEMCUE_TAILSCALE_CONNECT_TIMEOUT"); value != "" {
		c.Timeout, err = time.ParseDuration(value)
		if err != nil || c.Timeout < time.Second || c.Timeout > 30*time.Second {
			return Config{}, errors.New("MEMCUE_TAILSCALE_CONNECT_TIMEOUT must be between 1s and 30s")
		}
	}
	return c, nil
}

// Configure installs both resolver and dialer on this one PostgreSQL connection,
// retaining the DSN hostname and TLS ServerName. Off has no helper dependency.
func Configure(ctx context.Context, cfg *pgx.ConnConfig) error {
	mode, err := Mode()
	if err != nil || mode == "off" {
		return err
	}
	c, err := Settings(cfg.Host, strconv.Itoa(int(cfg.Port)))
	if err != nil {
		return err
	}
	if err := checkProfile(c); err != nil {
		return err
	}
	state, err := request(ctx, c, "status")
	if err != nil {
		return err
	}
	if state.State != "Running" {
		return errors.New("tailnet login or device approval required; run memcue connect login")
	}
	cfg.LookupFunc = func(ctx context.Context, host string) ([]string, error) { return Lookup(ctx, c, host) }
	cfg.DialFunc = func(ctx context.Context, network, address string) (net.Conn, error) {
		return Dial(ctx, c, network, address)
	}
	return nil
}
