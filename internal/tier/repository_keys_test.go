package tier

import (
	"os/exec"
	"testing"
)

func TestRepositoryKeysRejectNonGit(t *testing.T) {
	isolate(t)
	dir := t.TempDir()
	if out, err := exec.Command("git", "-C", dir, "rev-parse", "--show-toplevel").CombinedOutput(); err == nil {
		t.Fatalf("fixture inside git: %s", out)
	}
	if got := RepositoryKeys(dir, ""); len(got) != 0 {
		t.Fatalf("non-git directory has repository applicability: %v", got)
	}
}
