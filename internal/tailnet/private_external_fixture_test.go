package tailnet_test

import (
	"os"
	"testing"
)

// Keep real embedded identity fixtures private independently of the caller umask.
func privateFixtureDir(t *testing.T) string {
	t.Helper()
	dir := t.TempDir()
	if err := os.Chmod(dir, 0700); err != nil {
		t.Fatal(err)
	}
	return dir
}
