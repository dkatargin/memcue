package tailnet

import (
	"os"
	"testing"
)

// TempDir's numbered child follows the process umask, not the identity policy.
// Set the fixture precondition explicitly; negative tests change it afterwards.
func privateFixtureDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	return dir
}
