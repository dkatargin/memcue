package tailnet

import (
	"os"
	"syscall"
	"testing"
	"time"
)

// syntheticOwnershipInfo is invented metadata, not a foreign-owned filesystem entry.
type syntheticOwnershipInfo struct{ stat syscall.Stat_t }

func (i syntheticOwnershipInfo) Name() string       { return "synthetic-identity" }
func (i syntheticOwnershipInfo) Size() int64        { return 0 }
func (i syntheticOwnershipInfo) Mode() os.FileMode  { return 0600 }
func (i syntheticOwnershipInfo) ModTime() time.Time { return time.Time{} }
func (i syntheticOwnershipInfo) IsDir() bool        { return false }
func (i syntheticOwnershipInfo) Sys() any           { return &i.stat }

func TestOwnershipMetadataRestartRejectsForeignUID(t *testing.T) {
	owner := uint32(os.Geteuid())
	info := syntheticOwnershipInfo{stat: syscall.Stat_t{Uid: owner ^ 1}}
	if !info.Mode().IsRegular() || info.Mode().Perm() != 0600 || info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		t.Fatal("setup: expected a private regular synthetic entry")
	}
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok || stat == nil || stat.Uid == owner {
		t.Fatal("setup: expected usable synthetic metadata with foreign UID")
	}
	if err := validateIdentityEntry(info); err == nil {
		t.Fatal("validateIdentityEntry accepted synthetic foreign UID metadata; want rejection")
	}
}
