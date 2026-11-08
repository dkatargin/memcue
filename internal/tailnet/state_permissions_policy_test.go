package tailnet

import (
	"net"
	"os"
	"path/filepath"
	"syscall"
	"testing"
)

func requireFixtureMode(t *testing.T, path string, mode os.FileMode) {
	t.Helper()
	if err := os.Chmod(path, mode); err != nil {
		t.Fatal(err)
	}
	info, err := os.Lstat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != mode {
		t.Fatalf("fixture mode: got %v, want %v", info.Mode().Perm(), mode)
	}
	owner, ok := info.Sys().(*syscall.Stat_t)
	if !ok || owner.Uid != uint32(os.Geteuid()) {
		t.Fatal("fixture must belong to effective user")
	}
}

func TestAcquireRejectsExposedNestedIdentity(t *testing.T) {
	for _, directory := range []bool{false, true} {
		name := "file"
		if directory {
			name = "directory"
		}
		t.Run(name, func(t *testing.T) {
			dir := privateFixtureDir(t)
			requireFixtureMode(t, dir, 0700)
			nested := filepath.Join(dir, "node")
			if err := os.Mkdir(nested, 0700); err != nil {
				t.Fatal(err)
			}
			requireFixtureMode(t, nested, 0700)
			state := filepath.Join(nested, "tailscaled.state")
			if err := os.WriteFile(state, []byte("synthetic nested identity"), 0600); err != nil {
				t.Fatal(err)
			}
			requireFixtureMode(t, state, 0600)
			if directory {
				requireFixtureMode(t, nested, 0710)
			} else {
				requireFixtureMode(t, state, 0640)
			}
			release, err := acquire(Config{Dir: dir})
			if release != nil {
				defer release()
			}
			if err == nil {
				t.Fatal("acquire accepted exposed nested identity; want rejection")
			}
		})
	}
}

func TestAcquireRejectsSymlinkedIdentity(t *testing.T) {
	for _, kind := range []string{"file", "directory", "dangling"} {
		t.Run(kind, func(t *testing.T) {
			dir := privateFixtureDir(t)
			requireFixtureMode(t, dir, 0700)
			nested := filepath.Join(dir, "node")
			if err := os.Mkdir(nested, 0700); err != nil {
				t.Fatal(err)
			}
			requireFixtureMode(t, nested, 0700)
			targetDir := privateFixtureDir(t)
			requireFixtureMode(t, targetDir, 0700)
			target := filepath.Join(targetDir, "synthetic.state")
			switch kind {
			case "file":
				if err := os.WriteFile(target, []byte("synthetic external fixture"), 0600); err != nil {
					t.Fatal(err)
				}
				requireFixtureMode(t, target, 0600)
			case "directory":
				target = targetDir
			}
			link := filepath.Join(nested, "identity")
			if err := os.Symlink(target, link); err != nil {
				t.Fatal(err)
			}
			// Chmod on a symlink follows its target; inspect the link itself instead.
			info, err := os.Lstat(link)
			if err != nil {
				t.Fatal(err)
			}
			if info.Mode()&os.ModeSymlink == 0 {
				t.Fatal("fixture must be a symlink")
			}
			release, err := acquire(Config{Dir: dir})
			if release != nil {
				defer release()
			}
			if err == nil {
				t.Fatal("acquire accepted symlinked identity; want rejection")
			}
		})
	}
}

// These are supplemental controls, not new behavioral REDs.
func TestAcquireAcceptsPrivateIdentityAndOwnerSocket(t *testing.T) {
	for _, mode := range []os.FileMode{0600, 0400} {
		t.Run(mode.String(), func(t *testing.T) {
			dir := privateFixtureDir(t)
			requireFixtureMode(t, dir, 0700)
			nested := filepath.Join(dir, "node")
			if err := os.Mkdir(nested, 0700); err != nil {
				t.Fatal(err)
			}
			requireFixtureMode(t, nested, 0700)
			state := filepath.Join(nested, "tailscaled.state")
			const identity = "synthetic identity bytes must survive acquire"
			if err := os.WriteFile(state, []byte(identity), 0600); err != nil {
				t.Fatal(err)
			}
			requireFixtureMode(t, state, mode)
			cfg := Config{Dir: dir}
			path, closeDir, err := socketPath(cfg)
			if err != nil {
				t.Fatal(err)
			}
			defer closeDir()
			listener, err := net.Listen("unix", path)
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = listener.Close() }()
			socket := filepath.Join(dir, "helper.sock")
			requireFixtureMode(t, socket, 0777)
			info, err := os.Lstat(socket)
			if err != nil || info.Mode()&os.ModeSocket == 0 {
				t.Fatal("fixture must be an owner-owned Unix socket")
			}
			release, err := acquire(cfg)
			if release != nil {
				defer release()
			}
			if err != nil {
				t.Fatalf("private identity and owner socket rejected: %v", err)
			}
			// Read only this synthetic fixture to verify byte preservation.
			data, err := os.ReadFile(state)
			if err != nil || string(data) != identity {
				t.Fatal("acquire changed synthetic identity bytes")
			}
			info, err = os.Lstat(state)
			if err != nil || info.Mode().Perm() != mode {
				t.Fatal("acquire changed synthetic identity mode")
			}
		})
	}
}

// Supplemental coverage of the existing permission-bit rejection predicate.
func TestAcquireRejectsEveryGroupOtherPermissionBit(t *testing.T) {
	for _, bit := range []os.FileMode{0040, 0020, 0010, 0004, 0002, 0001} {
		t.Run((0600 | bit).String(), func(t *testing.T) {
			dir := privateFixtureDir(t)
			requireFixtureMode(t, dir, 0700)
			state := filepath.Join(dir, "tailscaled.state")
			if err := os.WriteFile(state, []byte("synthetic permission fixture"), 0600); err != nil {
				t.Fatal(err)
			}
			requireFixtureMode(t, state, 0600|bit)
			release, err := acquire(Config{Dir: dir})
			if release != nil {
				defer release()
			}
			if err == nil {
				t.Fatal("acquire accepted group/other permission bit; want rejection")
			}
		})
	}
}
