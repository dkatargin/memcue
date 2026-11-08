package main

import (
	"errors"
	"os"
)

// Historical dump/merge have explicit file operands and remain local. These
// implicit-base maintenance workflows require an explicit local invocation.
func remoteCommandAllowed(command string) error {
	if os.Getenv("MEMCUE_POSTGRES_DSN") == "" {
		return nil
	}
	switch command {
	case "migrate", "import", "install", "notes", "dream", "reindex":
		return errors.New("command unavailable for PostgreSQL; explicitly unset MEMCUE_POSTGRES_DSN for local maintenance")
	}
	return nil
}
