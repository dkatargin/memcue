package tailnet

import (
	"context"
	"os"
	"path/filepath"
	"syscall"
	"testing"
	"time"
)

func TestRepairSpecialFileOpensNeverBlock(t *testing.T) {
	for _, kind := range []string{"key", "profile-check", "profile-acquire"} {
		t.Run(kind, func(t *testing.T) {
			dir := privateFixtureDir(t)
			path := filepath.Join(dir, "profile.json")
			if kind == "key" {
				path = filepath.Join(dir, "key.fifo")
			}
			if err := syscall.Mkfifo(path, 0600); err != nil {
				t.Fatal(err)
			}
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			done := make(chan error, 1)
			go func() {
				switch kind {
				case "key":
					done <- Run(ctx, Config{Dir: filepath.Join(dir, "identity"), KeyFile: path}, true, make(chan struct{}))
				case "profile-check":
					done <- checkProfile(Config{Dir: dir})
				default:
					release, err := acquire(Config{Dir: dir})
					if release != nil {
						release()
					}
					done <- err
				}
			}()
			select {
			case err := <-done:
				if err == nil {
					t.Fatal("FIFO accepted")
				}
			case <-time.After(150 * time.Millisecond):
				cancel()
				fd, err := syscall.Open(path, syscall.O_WRONLY|syscall.O_NONBLOCK, 0)
				if err != nil {
					t.Fatal(err)
				}
				_ = syscall.Close(fd)
				select {
				case <-done:
				case <-time.After(time.Second):
					t.Fatal("safety release failed")
				}
				t.Fatal("special file open blocked before regular-file validation")
			}
		})
	}
}

func TestRepairFileOpenRegularAndSymlinkControls(t *testing.T) {
	c := Config{Dir: privateFixtureDir(t), Hostname: "fixture", ControlURL: "https://control.invalid", Host: "database.memcue.test", Port: "5432"}
	profile := filepath.Join(c.Dir, "profile.json")
	if err := os.WriteFile(profile, profileBytes(c), 0600); err != nil {
		t.Fatal(err)
	}
	if err := checkProfile(c); err != nil {
		t.Fatalf("regular private profile rejected: %v", err)
	}
	target := filepath.Join(privateFixtureDir(t), "profile")
	if err := os.Rename(profile, target); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(target, profile); err != nil {
		t.Fatal(err)
	}
	if err := checkProfile(c); err == nil {
		t.Fatal("symlink profile accepted")
	}
	keytarget := filepath.Join(privateFixtureDir(t), "key")
	if err := os.WriteFile(keytarget, []byte("synthetic"), 0600); err != nil {
		t.Fatal(err)
	}
	keylink := filepath.Join(privateFixtureDir(t), "keylink")
	if err := os.Symlink(keytarget, keylink); err != nil {
		t.Fatal(err)
	}
	err := Run(context.Background(), Config{Dir: privateFixtureDir(t), ControlURL: "http://127.0.0.1:58081", KeyFile: keylink}, true, make(chan struct{}))
	if err == nil || err.Error() != "cannot open bootstrap key file" {
		t.Fatalf("symlink key was not rejected at open: %v", err)
	}
}
