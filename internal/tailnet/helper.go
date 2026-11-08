// Package tailnet owns Memcue's optional persistent userspace transport.
package tailnet

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"sync"
	"syscall"
	"time"
)

type Config struct {
	Dir, Hostname, ControlURL, Host, Port, KeyFile string
	Timeout                                        time.Duration
}
type State struct {
	NodeID  string `json:"node_id,omitempty"`
	Running bool   `json:"running"`
	State   string `json:"state"`
	AuthURL string `json:"auth_url,omitempty"`
}
type node interface {
	Status(context.Context) (State, error)
	Login(context.Context) error
	Lookup(context.Context, string) ([]string, error)
	Dial(context.Context, string) (net.Conn, error)
	Close() error
}
type message struct {
	Version int    `json:"version"`
	Op      string `json:"op"`
	Host    string `json:"host,omitempty"`
	Port    string `json:"port,omitempty"`
}
type reply struct {
	State
	Error string   `json:"error,omitempty"`
	IPs   []string `json:"ips,omitempty"`
}

var errHelper = errors.New("embedded transport unavailable; start memcue connect serve, then memcue connect login")

func socketPath(c Config) (string, func(), error) {
	path := filepath.Join(c.Dir, "helper.sock")
	if len(path) < 104 {
		return path, func() {}, nil
	}
	if runtime.GOOS != "linux" {
		return "", nil, errors.New("tailnet state path is too long for Unix IPC")
	}
	dir, err := os.Open(c.Dir)
	if err != nil {
		return "", nil, errHelper
	}
	return fmt.Sprintf("/proc/self/fd/%d/helper.sock", dir.Fd()), func() { _ = dir.Close() }, nil
}
func timeout(c Config) time.Duration {
	if c.Timeout > 0 {
		return c.Timeout
	}
	return 5 * time.Second
}
func privateDir(dir string) error {
	fi, err := os.Lstat(dir)
	if err != nil || !fi.IsDir() || fi.Mode().Perm() != 0700 {
		return errors.New("tailnet state directory must be owned by this user with mode 0700 and no symlink")
	}
	st, ok := fi.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != uint32(os.Geteuid()) {
		return errors.New("tailnet state directory has the wrong owner")
	}
	return nil
}
func profileBytes(c Config) []byte {
	profile := struct {
		Version                          int
		Hostname, ControlURL, Host, Port string
	}{1, c.Hostname, c.ControlURL, c.Host, c.Port}
	data, _ := json.Marshal(profile)
	return data
}
func checkProfile(c Config) error {
	if err := privateDir(c.Dir); err != nil {
		return err
	}
	fd, err := syscall.Open(filepath.Join(c.Dir, "profile.json"), syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if err != nil {
		return errHelper
	}
	f := os.NewFile(uintptr(fd), "profile.json")
	defer func() { _ = f.Close() }()
	fi, err := f.Stat()
	if err != nil || !fi.Mode().IsRegular() || fi.Mode().Perm() != 0600 {
		return errHelper
	}
	owner, ok := fi.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
		return errHelper
	}
	data, err := io.ReadAll(io.LimitReader(f, 4097))
	if err != nil || !bytes.Equal(data, profileBytes(c)) {
		return errors.New("tailnet helper profile differs; use a separate state directory or matching configuration")
	}
	return nil
}

func validateIdentityEntry(info os.FileInfo) error {
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || owner == nil || owner.Uid != uint32(os.Geteuid()) {
		return errors.New("tailnet identity entries must belong to the effective user")
	}
	if info.Mode()&os.ModeSymlink != 0 {
		return errors.New("tailnet identity entries must not be symlinks")
	}
	if (info.Mode().IsRegular() || info.IsDir()) && info.Mode().Perm()&0077 != 0 {
		return errors.New("tailnet identity entries must be private")
	}
	return nil
}

// privateIdentityEntries checks metadata without opening node identity files.
func privateIdentityEntries(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	for _, entry := range entries {
		info, err := os.Lstat(filepath.Join(dir, entry.Name()))
		if err != nil {
			return err
		}
		if err := validateIdentityEntry(info); err != nil {
			return err
		}
		if info.IsDir() {
			if err := privateIdentityEntries(filepath.Join(dir, entry.Name())); err != nil {
				return err
			}
		}
	}
	return nil
}
func acquire(c Config) (func(), error) {
	if err := os.MkdirAll(c.Dir, 0700); err != nil {
		return nil, errHelper
	}
	if err := privateDir(c.Dir); err != nil {
		return nil, err
	}
	if err := privateIdentityEntries(c.Dir); err != nil {
		return nil, err
	}
	fd, err := syscall.Open(filepath.Join(c.Dir, "owner.lock"), syscall.O_RDWR|syscall.O_CREAT|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return nil, errors.New("cannot open private tailnet ownership lock")
	}
	f := os.NewFile(uintptr(fd), "owner.lock")
	fi, err := f.Stat()
	if err != nil || !fi.Mode().IsRegular() || fi.Mode().Perm() != 0600 {
		_ = f.Close()
		return nil, errors.New("tailnet ownership lock must be a private regular file")
	}
	if err := syscall.Flock(fd, syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = f.Close()
		return nil, errors.New("tailnet identity already has an owner; use the existing helper")
	}
	release := func() { _ = syscall.Flock(fd, syscall.LOCK_UN); _ = f.Close() }
	data := profileBytes(c)
	profilePath := filepath.Join(c.Dir, "profile.json")
	pfd, e := syscall.Open(profilePath, syscall.O_RDONLY|syscall.O_NOFOLLOW|syscall.O_NONBLOCK, 0)
	if os.IsNotExist(e) {
		pfd, e = syscall.Open(profilePath, syscall.O_WRONLY|syscall.O_CREAT|syscall.O_EXCL|syscall.O_NOFOLLOW, 0600)
		if e != nil {
			release()
			return nil, errHelper
		}
		pf := os.NewFile(uintptr(pfd), "profile.json")
		_, e = pf.Write(data)
		if e == nil {
			e = pf.Sync()
		}
		_ = pf.Close()
	} else if e == nil {
		pf := os.NewFile(uintptr(pfd), "profile.json")
		info, se := pf.Stat()
		existing, re := io.ReadAll(io.LimitReader(pf, 4097))
		_ = pf.Close()
		if se != nil || re != nil || !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || !bytes.Equal(existing, data) {
			e = errors.New("tailnet profile differs or has unsafe permissions; select a separate private state directory")
		}
	}
	if e != nil {
		release()
		return nil, errors.New("tailnet profile differs or has unsafe permissions; select a separate private state directory")
	}
	return release, nil
}
func serve(ctx context.Context, c Config, n node, ready chan<- struct{}) error {
	release, err := acquire(c)
	if err != nil {
		return err
	}
	defer release()
	return serveOwned(ctx, c, n, ready)
}
func serveOwned(ctx context.Context, c Config, n node, ready chan<- struct{}) error {
	defer func() { _ = n.Close() }()
	ctx, stopServe := context.WithCancel(ctx)
	defer stopServe()
	if fi, err := os.Lstat(filepath.Join(c.Dir, "helper.sock")); err == nil {
		if fi.Mode()&os.ModeSocket == 0 {
			return errors.New("tailnet IPC path is not a socket")
		}
		if err := os.Remove(filepath.Join(c.Dir, "helper.sock")); err != nil {
			return errHelper
		}
	} else if !os.IsNotExist(err) {
		return errHelper
	}
	path, closeDir, err := socketPath(c)
	if err != nil {
		return err
	}
	defer closeDir()
	l, err := net.Listen("unix", path)
	if err != nil {
		return errHelper
	}
	if err := os.Chmod(filepath.Join(c.Dir, "helper.sock"), 0600); err != nil {
		_ = l.Close()
		return errHelper
	}
	defer func() { _ = l.Close() }()
	stop := context.AfterFunc(ctx, func() { _ = l.Close() })
	defer stop()
	close(ready)
	var wg sync.WaitGroup
	defer wg.Wait()
	for {
		conn, err := l.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return errHelper
		}
		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() { _ = conn.Close() }()
			closeOnCancel := context.AfterFunc(ctx, func() { _ = conn.Close() })
			defer closeOnCancel()
			_ = conn.SetDeadline(time.Now().Add(timeout(c)))
			var m message
			data, err := bufio.NewReaderSize(conn, 4096).ReadSlice('\n')
			if err != nil || json.Unmarshal(data, &m) != nil {
				return
			}
			r := reply{}
			requestCtx, cancel := context.WithTimeout(ctx, timeout(c))
			defer cancel()
			if m.Version != 1 {
				r.Error = "unsupported helper protocol"
			} else if m.Op == "off" {
				r.State = State{State: "Stopping"}
				defer stopServe()
			} else {
				state, err := n.Status(requestCtx)
				if err != nil {
					r.Error = "tailnet status unavailable"
				} else {
					state.AuthURL = ""
					r.State = state
					switch m.Op {
					case "status":
					case "login":
						if err := n.Login(requestCtx); err != nil {
							r.Error = "tailnet login could not start"
							break
						}
						logged, err := n.Status(requestCtx)
						if err != nil {
							r.Error = "tailnet login status unavailable"
						} else {
							r.State = logged
						}
					case "lookup", "dial":
						if state.State != "Running" {
							r.Error = "tailnet login or device approval required; run memcue connect login"
							break
						}
						ips, err := n.Lookup(requestCtx, c.Host)
						if err != nil || len(ips) == 0 {
							r.Error = "backend is not an approved tailnet peer"
							break
						}
						if m.Op == "lookup" {
							if m.Host != c.Host {
								r.Error = "unconfigured DNS destination"
							} else {
								r.IPs = ips
							}
						} else {
							if m.Port != c.Port || !slices.Contains(ips, m.Host) {
								r.Error = "unconfigured backend destination"
								break
							}
							upstream, err := n.Dial(requestCtx, net.JoinHostPort(m.Host, c.Port))
							if err != nil {
								r.Error = "tailnet backend unavailable"
								break
							}
							defer func() { _ = upstream.Close() }()
							stopUpstream := context.AfterFunc(ctx, func() { _ = upstream.Close() })
							defer stopUpstream()
							if json.NewEncoder(conn).Encode(r) != nil {
								return
							}
							_ = conn.SetDeadline(time.Now().Add(5 * time.Minute))
							_ = upstream.SetDeadline(time.Now().Add(5 * time.Minute))
							copied := make(chan struct{})
							go func() { _, _ = io.Copy(upstream, conn); _ = upstream.Close(); close(copied) }()
							_, _ = io.Copy(conn, upstream)
							_ = conn.Close()
							_ = upstream.Close()
							<-copied
							return
						}
					default:
						r.Error = "unsupported helper request"
					}
				}
			}
			_ = json.NewEncoder(conn).Encode(r)
		}()
	}
}
func exchange(ctx context.Context, c Config, m message) (net.Conn, reply, error) {
	if err := privateDir(c.Dir); err != nil {
		return nil, reply{}, err
	}
	fi, err := os.Lstat(filepath.Join(c.Dir, "helper.sock"))
	if err != nil || fi.Mode()&os.ModeSocket == 0 || fi.Mode().Perm() != 0600 {
		return nil, reply{}, errHelper
	}
	owner, ok := fi.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
		return nil, reply{}, errHelper
	}
	d := net.Dialer{Timeout: timeout(c)}
	path, closeDir, err := socketPath(c)
	if err != nil {
		return nil, reply{}, err
	}
	defer closeDir()
	conn, err := d.DialContext(ctx, "unix", path)
	if err != nil {
		return nil, reply{}, errHelper
	}
	deadline := time.Now().Add(timeout(c))
	if until, ok := ctx.Deadline(); ok && until.Before(deadline) {
		deadline = until
	}
	_ = conn.SetDeadline(deadline)
	stop := context.AfterFunc(ctx, func() { _ = conn.Close() })
	defer stop()
	if json.NewEncoder(conn).Encode(m) != nil {
		_ = conn.Close()
		return nil, reply{}, errHelper
	}
	data, err := bufio.NewReaderSize(conn, 4096).ReadSlice('\n')
	var r reply
	if err != nil || json.Unmarshal(data, &r) != nil {
		_ = conn.Close()
		return nil, reply{}, errHelper
	}
	if r.Error != "" {
		_ = conn.Close()
		return nil, r, errors.New(r.Error)
	}
	return conn, r, nil
}
func request(ctx context.Context, c Config, op string) (State, error) {
	conn, r, err := exchange(ctx, c, message{Version: 1, Op: op})
	if err != nil {
		return State{}, err
	}
	_ = conn.Close()
	return r.State, nil
}

// Admin performs an explicit local helper administration operation.
func Admin(ctx context.Context, c Config, op string) (State, error) {
	if op != "status" && op != "login" && op != "off" {
		return State{}, errors.New("unsupported administration operation")
	}
	if op == "login" && c.Host != "" {
		if err := checkProfile(c); err != nil {
			return State{}, err
		}
	}
	return request(ctx, c, op)
}
