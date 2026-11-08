package tailnet

import (
	"os"
	"syscall"
	"testing"
)

// Metadata and modes here are explicitly synthetic.
type ownershipControlInfo struct {
	syntheticOwnershipInfo
	metadata any
	mode     os.FileMode
}

func (i ownershipControlInfo) Sys() any          { return i.metadata }
func (i ownershipControlInfo) Mode() os.FileMode { return i.mode }
func (i ownershipControlInfo) IsDir() bool       { return i.mode.IsDir() }

func TestOwnershipMetadataSupplementalControls(t *testing.T) {
	owner := &syscall.Stat_t{Uid: uint32(os.Geteuid())}
	for _, tc := range []struct {
		name     string
		metadata any
		mode     os.FileMode
		reject   bool
	}{
		{"matching-private-file", owner, 0600, false},
		{"matching-private-directory", owner, os.ModeDir | 0700, false},
		{"unavailable", nil, 0600, true},
		{"wrong-type", struct{}{}, 0600, true},
		{"typed-nil", (*syscall.Stat_t)(nil), 0600, true},
		{"matching-public-file", owner, 0644, true},
		{"matching-public-directory", owner, os.ModeDir | 0755, true},
		{"matching-symlink", owner, os.ModeSymlink | 0600, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			info := ownershipControlInfo{metadata: tc.metadata, mode: tc.mode}
			if err := validateIdentityEntry(info); (err != nil) != tc.reject {
				t.Fatalf("validateIdentityEntry error = %v; want rejection %v", err, tc.reject)
			}
		})
	}
}
