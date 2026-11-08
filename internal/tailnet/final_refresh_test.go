package tailnet_test

import (
	"bufio"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/juev/memcue/internal/store"
	"github.com/juev/memcue/internal/tailnet"
	"tailscale.com/derp/derpserver"
	"tailscale.com/envknob"
	"tailscale.com/tsnet"
	"tailscale.com/types/key"
)

// This is a supervised disposable network fixture, never a live tailnet. It is
// supplemental final-source coverage of accepted policy and helper machinery.
func TestFinalACLAndOutageRefresh(t *testing.T) {
	hs, binary, adminDSN := os.Getenv("MEMCUE_FINAL_HEADSCALE_BINARY"), os.Getenv("MEMCUE_TEST_BIN"), os.Getenv("MEMCUE_TEST_POSTGRES_DSN")
	if hs == "" || binary == "" || adminDSN == "" {
		t.Skip("requires owned Headscale/PostgreSQL/native fixture")
	}
	envknob.SetNoLogsNoSupport()
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Second)
	defer cancel()
	root, rootErr := os.MkdirTemp(os.TempDir(), "net-")
	if rootErr != nil {
		t.Fatal(rootErr)
	}
	reportPath := os.Getenv("MEMCUE_FINAL_NETWORK_REPORT")
	report := map[string]any{"fixture_root": root}
	defer func() {
		if reportPath != "" {
			data, _ := json.MarshalIndent(report, "", "  ")
			_ = os.WriteFile(reportPath, data, 0600)
		}
	}()
	writeJSON := func(path string, value any) {
		t.Helper()
		b, e := json.Marshal(value)
		if e != nil {
			t.Fatal(e)
		}
		if e = os.WriteFile(path, b, 0600); e != nil {
			t.Fatal(e)
		}
	}
	port := func() string {
		t.Helper()
		l, e := net.Listen("tcp", "127.0.0.1:0")
		if e != nil {
			t.Fatal(e)
		}
		defer func() { _ = l.Close() }()
		return strconv.Itoa(l.Addr().(*net.TCPAddr).Port)
	}
	controlPort := port()
	control := "http://127.0.0.1:" + controlPort
	var relayRequests atomic.Int64
	relay := derpserver.New(key.NewNode(), func(string, ...any) {})
	relayHTTP := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.EqualFold(r.Header.Get("Upgrade"), "derp") {
			relayRequests.Add(1)
		}
		derpserver.Handler(relay).ServeHTTP(w, r)
	}))
	defer relayHTTP.Close()
	defer func() { _ = relay.Close() }()
	relayPort := relayHTTP.Listener.Addr().(*net.TCPAddr).Port
	derpMap := filepath.Join(root, "derp.json")
	if e := os.WriteFile(derpMap, []byte(fmt.Sprintf(`regions:
  901:
    regionid: 901
    regioncode: owned
    regionname: Owned local relay
    nodes:
      - name: 901a
        regionid: 901
        hostname: 127.0.0.1
        ipv4: 127.0.0.1
        ipv6: none
        stunport: -1
        derpport: %d
        insecurefortests: true
`, relayPort)), 0600); e != nil {
		t.Fatal(e)
	}
	config := filepath.Join(root, "headscale.json")
	writeJSON(config, map[string]any{
		"server_url": control, "listen_addr": "127.0.0.1:" + controlPort, "metrics_listen_addr": "127.0.0.1:" + port(), "grpc_listen_addr": "127.0.0.1:" + port(),
		"noise": map[string]any{"private_key_path": filepath.Join(root, "noise.key")}, "prefixes": map[string]any{"v4": "100.64.0.0/24", "v6": "fd7a:115c:a1e0::/64"},
		"database":    map[string]any{"type": "sqlite", "sqlite": map[string]any{"path": filepath.Join(root, "headscale.db")}},
		"unix_socket": filepath.Join(root, "headscale.sock"), "unix_socket_permission": "0600", "policy": map[string]any{"mode": "database"},
		"derp":                  map[string]any{"server": map[string]any{"enabled": false}, "urls": []string{}, "paths": []string{derpMap}, "auto_update_enabled": false},
		"dns":                   map[string]any{"magic_dns": true, "base_domain": "fixture.invalid", "override_local_dns": false, "nameservers": map[string]any{"global": []string{}}},
		"disable_check_updates": true, "logtail": map[string]any{"enabled": false}, "log": map[string]any{"level": "warn"},
	})
	logFile, e := os.OpenFile(filepath.Join(root, "headscale.log"), os.O_CREATE|os.O_WRONLY, 0600)
	if e != nil {
		t.Fatal(e)
	}
	defer func() { _ = logFile.Close() }()
	controlProcess := exec.CommandContext(ctx, hs, "-c", config, "serve")
	controlProcess.Stdout = logFile
	controlProcess.Stderr = logFile
	controlProcess.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	if e = controlProcess.Start(); e != nil {
		t.Fatalf("SETUP: control start: %v", e)
	}
	controlDone := make(chan error, 1)
	go func() { controlDone <- controlProcess.Wait() }()
	alive := true
	stopControl := func() {
		if !alive {
			return
		}
		_ = syscall.Kill(-controlProcess.Process.Pid, syscall.SIGTERM)
		select {
		case <-controlDone:
		case <-time.After(3 * time.Second):
			_ = syscall.Kill(-controlProcess.Process.Pid, syscall.SIGKILL)
			<-controlDone
		}
		alive = false
	}
	defer stopControl()
	client := &http.Client{Timeout: time.Second}
	ready := func() bool {
		if !alive || controlProcess.Process.Signal(syscall.Signal(0)) != nil {
			return false
		}
		res, e := client.Get(control + "/health")
		if e != nil {
			return false
		}
		defer func() { _ = res.Body.Close() }()
		return res.StatusCode == 200
	}
	until := func(label string, check func() bool) {
		t.Helper()
		deadline := time.Now().Add(12 * time.Second)
		for time.Now().Before(deadline) {
			if check() {
				return
			}
			select {
			case <-ctx.Done():
				t.Fatalf("SETUP/phase deadline: %s", label)
			case <-time.After(100 * time.Millisecond):
			}
		}
		t.Fatalf("SETUP/phase readiness failed: %s", label)
	}
	until("supervised control HTTP readiness", ready)
	stat, e := os.ReadFile(fmt.Sprintf("/proc/%d/stat", controlProcess.Process.Pid))
	if e != nil {
		t.Fatal("SETUP: control PID identity unavailable")
	}
	report["control_pid"] = controlProcess.Process.Pid
	report["control_start_stat"] = string(stat)
	hsCall := func(args ...string) []byte {
		t.Helper()
		if !ready() {
			t.Fatal("SETUP: control disappeared before admin operation")
		}
		cmd := exec.CommandContext(ctx, hs, append([]string{"-c", config, "-o", "json"}, args...)...)
		out, e := cmd.Output()
		if e != nil {
			t.Fatalf("SETUP: Headscale %s failed: %v", args[0], e)
		}
		return out
	}
	var user struct {
		ID uint64 `json:"id"`
	}
	if e = json.Unmarshal(hsCall("users", "create", "owned-fixture"), &user); e != nil || user.ID == 0 {
		t.Fatal("SETUP: user creation result")
	}
	var auth struct {
		Key string `json:"key"`
	}
	if e = json.Unmarshal(hsCall("preauthkeys", "create", "--user", strconv.FormatUint(user.ID, 10), "--reusable", "--expiration", "1h"), &auth); e != nil || auth.Key == "" {
		t.Fatal("SETUP: synthetic key creation")
	}
	keyfile := filepath.Join(root, "bootstrap.key")
	if e = os.WriteFile(keyfile, []byte(auth.Key), 0600); e != nil {
		t.Fatal(e)
	}
	policyFile := filepath.Join(root, "policy.json")
	policy := func(dbPort string) {
		t.Helper()
		writeJSON(policyFile, map[string]any{"acls": []any{map[string]any{"action": "accept", "src": []string{"*"}, "dst": []string{"*:" + dbPort}}}})
		hsCall("policy", "set", "--file", policyFile)
	}
	policy("5432")
	// Preprovision schema with admin, then use a separate DML-only role throughout the tailnet route.
	adminStore, e := store.OpenPostgresRequest(adminDSN, 4*time.Second)
	if e != nil {
		t.Fatal("SETUP: PostgreSQL admin open")
	}
	_ = adminStore.Close()
	admin, e := pgx.Connect(ctx, adminDSN)
	if e != nil {
		t.Fatal("SETUP: PostgreSQL observer")
	}
	defer func() { _ = admin.Close(context.Background()) }()
	var secret [16]byte
	if _, e = rand.Read(secret[:]); e != nil {
		t.Fatal(e)
	}
	password := hex.EncodeToString(secret[:])
	_, e = admin.Exec(ctx, "CREATE ROLE owned_runtime LOGIN PASSWORD '"+password+"'; REVOKE CREATE ON DATABASE postgres FROM PUBLIC; GRANT CONNECT ON DATABASE postgres TO owned_runtime; GRANT USAGE ON SCHEMA memcue TO owned_runtime; GRANT SELECT ON memcue.version TO owned_runtime; GRANT SELECT, INSERT ON memcue.facts TO owned_runtime")
	if e != nil {
		t.Fatal("SETUP: DML-only role provisioning")
	}
	dbnode := &tsnet.Server{Dir: filepath.Join(root, "database"), Hostname: "owned-database", ControlURL: control, AuthKey: auth.Key, UserLogf: func(string, ...any) {}, Logf: func(string, ...any) {}}
	up, e := dbnode.Up(ctx)
	if e != nil {
		_ = dbnode.Close()
		t.Fatalf("SETUP: database node readiness: %v", e)
	}
	defer func() { _ = dbnode.Close() }()
	listener, e := dbnode.Listen("tcp", ":5432")
	if e != nil {
		t.Fatal("SETUP: database listener")
	}
	var bridgeWG sync.WaitGroup
	var protocolBytes, accepted atomic.Int64
	backend := os.Getenv("MEMCUE_TEST_POSTGRES_ADDR")
	bridgeDone := make(chan struct{})
	go func() {
		defer close(bridgeDone)
		for {
			conn, e := listener.Accept()
			if e != nil {
				return
			}
			accepted.Add(1)
			bridgeWG.Add(1)
			go func() {
				defer bridgeWG.Done()
				defer func() { _ = conn.Close() }()
				up, e := (&net.Dialer{}).DialContext(ctx, "tcp", backend)
				if e != nil {
					return
				}
				defer func() { _ = up.Close() }()
				stop := context.AfterFunc(ctx, func() { _ = conn.Close(); _ = up.Close() })
				defer stop()
				done := make(chan struct{})
				go func() {
					defer close(done)
					buf := make([]byte, 4096)
					for {
						n, e := conn.Read(buf)
						protocolBytes.Add(int64(n))
						if n > 0 {
							if _, we := up.Write(buf[:n]); we != nil {
								break
							}
						}
						if e != nil {
							break
						}
					}
					_ = up.Close()
				}()
				_, _ = io.Copy(conn, up)
				_ = conn.Close()
				_ = up.Close()
				<-done
			}()
		}
	}()
	defer func() { _ = listener.Close(); <-bridgeDone; cancel(); bridgeWG.Wait() }()
	host := strings.TrimSuffix(up.Self.DNSName, ".")
	cfg := tailnet.Config{Dir: filepath.Join(root, "helper"), Hostname: "owned-client", ControlURL: control, Host: host, Port: "5432", KeyFile: keyfile, Timeout: 10 * time.Second}
	helperReady := make(chan struct{})
	helperDone := make(chan error, 1)
	helperCtx, stopHelper := context.WithCancel(ctx)
	defer stopHelper()
	go func() { helperDone <- tailnet.Run(helperCtx, cfg, true, helperReady) }()
	select {
	case <-helperReady:
	case e := <-helperDone:
		t.Fatalf("SETUP: helper readiness: %v", e)
	case <-ctx.Done():
		t.Fatal("SETUP: helper timeout")
	}
	defer func() { stopHelper(); <-helperDone }()
	t.Setenv("MEMCUE_TAILSCALE_MODE", "embedded")
	t.Setenv("MEMCUE_TAILSCALE_STATE_DIR", cfg.Dir)
	t.Setenv("MEMCUE_TAILSCALE_HOSTNAME", cfg.Hostname)
	t.Setenv("MEMCUE_TAILSCALE_CONTROL_URL", control)
	t.Setenv("MEMCUE_TAILSCALE_ALLOW_LOOPBACK_CONTROL", "1")
	remote := &url.URL{Scheme: "postgres", Host: net.JoinHostPort(host, "5432"), User: url.UserPassword("owned_runtime", password), Path: "/postgres", RawQuery: "sslmode=disable"}
	t.Setenv("MEMCUE_POSTGRES_DSN", remote.String())
	t.Setenv("MEMCUE_FACTS", filepath.Join(root, "must-not-create"))
	t.Setenv("MEMCUE_STATE_DIR", filepath.Join(root, "client-state"))
	native := func(args ...string) (string, error) {
		cmd := exec.CommandContext(ctx, binary, args...)
		out, e := cmd.CombinedOutput()
		return string(out), e
	}
	noFallback := func() {
		t.Helper()
		if _, e := os.Stat(os.Getenv("MEMCUE_FACTS")); !os.IsNotExist(e) {
			t.Fatal("remote call created local fallback")
		}
	}
	if !ready() {
		t.Fatal("SETUP: control gone before positive route")
	}
	id, e := native("add", "-source", "user", "--", "Prefer synthetic network review examples.")
	if e != nil {
		t.Fatalf("positive runtime-role native add failed: %v", e)
	}
	id = strings.TrimSpace(id)
	var count int
	if e = admin.QueryRow(ctx, "SELECT count(*) FROM memcue.facts WHERE id=$1", id).Scan(&count); e != nil || count != 1 {
		t.Fatal("independent positive durable observation failed")
	}
	report["runtime_role_positive"] = true
	if _, e = native("history", id); e != nil {
		t.Fatal("positive runtime-role history failed")
	}
	until("own relay sessions", func() bool { return relayRequests.Load() >= 2 })
	report["relay_sessions"] = relayRequests.Load()
	// Drop the helper's actual dial ACK. exchange has not returned a DB stream,
	// so pgx cannot send startup/auth/query/commit bytes at this boundary.
	actualSocket := filepath.Join(cfg.Dir, "helper-real.sock")
	originalSocket := filepath.Join(cfg.Dir, "helper.sock")
	if e = os.Rename(originalSocket, actualSocket); e != nil {
		t.Fatal("SETUP: IPC proxy placement")
	}
	proxy, e := net.Listen("unix", originalSocket)
	if e != nil {
		t.Fatal("SETUP: IPC proxy")
	}
	if e = os.Chmod(originalSocket, 0600); e != nil {
		t.Fatal(e)
	}
	var dropped atomic.Int64
	var proxyWG sync.WaitGroup
	proxyDone := make(chan struct{})
	go func() {
		defer close(proxyDone)
		for {
			c, e := proxy.Accept()
			if e != nil {
				return
			}
			proxyWG.Add(1)
			go func() {
				defer proxyWG.Done()
				defer func() { _ = c.Close() }()
				_ = c.SetDeadline(time.Now().Add(5 * time.Second))
				line, e := bufio.NewReader(c).ReadBytes('\n')
				if e != nil {
					return
				}
				var msg struct{ Op string }
				if json.Unmarshal(line, &msg) != nil {
					return
				}
				up, e := net.Dial("unix", actualSocket)
				if e != nil {
					return
				}
				defer func() { _ = up.Close() }()
				_ = up.SetDeadline(time.Now().Add(5 * time.Second))
				if _, e = up.Write(line); e != nil {
					return
				}
				ack, e := bufio.NewReader(up).ReadBytes('\n')
				if e != nil {
					return
				}
				if msg.Op == "dial" {
					dropped.Add(1)
					return
				}
				_, _ = c.Write(ack)
			}()
		}
	}()
	beforeBytes, beforeAccept := protocolBytes.Load(), accepted.Load()
	var beforeRows int
	if e = admin.QueryRow(ctx, "SELECT count(*) FROM memcue.facts").Scan(&beforeRows); e != nil {
		t.Fatal(e)
	}
	refused, err := native("correct", "-expected-version", "1", "--", id, "Prefer synthetic network examples with reasons.")
	_ = proxy.Close()
	<-proxyDone
	proxyWG.Wait()
	_ = os.Remove(originalSocket)
	if e = os.Rename(actualSocket, originalSocket); e != nil {
		t.Fatal(e)
	}
	if dropped.Load() == 0 || accepted.Load() <= beforeAccept {
		t.Fatal("SETUP: actual helper dial ACK/DB TCP opportunity not reached")
	}
	if err == nil || strings.Contains(strings.ToUpper(refused), "UNKNOWN OUTCOME") {
		t.Fatal("pre-protocol IPC ACK loss misclassified")
	}
	if protocolBytes.Load() != beforeBytes {
		t.Fatal("IPC ACK loss forwarded PostgreSQL protocol bytes")
	}
	var afterRows int
	if e = admin.QueryRow(ctx, "SELECT count(*) FROM memcue.facts").Scan(&afterRows); e != nil || afterRows != beforeRows {
		t.Fatal("IPC ACK loss changed durable history")
	}
	report["ipc_ack_loss"] = map[string]any{"dropped": dropped.Load(), "new_tcp_streams": accepted.Load() - beforeAccept, "postgres_bytes": protocolBytes.Load() - beforeBytes, "history_unchanged": true, "classification": "ordinary pre-protocol failure"}
	noFallback()
	// A visible peer is insufficient authorization for the configured DB port.
	policy("5433")
	var denied bool
	until("ACL denial", func() bool {
		if !ready() {
			t.Fatal("SETUP: control gone during ACL assertion")
		}
		ips, e := tailnet.Lookup(ctx, cfg, host)
		if e != nil || len(ips) == 0 {
			return false
		}
		_, e = native("history", id)
		denied = e != nil
		return denied
	})
	report["visible_peer_db_port_denied"] = denied
	noFallback()
	policy("5432")
	until("restored DB port recovery", func() bool {
		if !ready() {
			t.Fatal("SETUP: control gone during recovery")
		}
		_, e := native("history", id)
		return e == nil
	})
	report["acl_restored_recovery"] = true
	// Deliberately stop supervised control plus relay. A cached direct path may
	// remain usable; record that truth rather than asserting revocation by outage.
	stopControl()
	_ = relay.Close()
	relayHTTP.Close()
	cached, e := native("history", id)
	report["cached_control_relay_loss"] = map[string]any{"native_success": e == nil, "explicit_failure": e != nil, "response_nonempty": strings.TrimSpace(cached) != ""}
	noFallback()
	if e == nil && !strings.Contains(cached, id) {
		t.Fatal("cached success did not contain durable ID")
	}
	_ = listener.Close()
	<-bridgeDone
	if _, e = native("history", id); e == nil {
		t.Fatal("backend listener loss falsely succeeded")
	}
	noFallback()
	report["backend_listener_loss_refused"] = true
	report["control_stopped"] = !alive
	t.Log("final isolated runtime-role/visible-peer ACL deny+restore, real IPC ACK loss, cached control+relay loss and listener-loss matrix executed")
}
