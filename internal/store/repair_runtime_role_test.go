package store

import (
	"context"
	"github.com/jackc/pgx/v5"
	"os"
	"testing"
)

func TestRepairProvisionedRuntimeRoleNeedsNoDDL(t *testing.T) {
	dsn := os.Getenv("MEMCUE_REPAIR_RUNTIME_DSN")
	if dsn == "" {
		t.Skip("isolated preprovisioned runtime role required")
	}
	c, err := pgx.Connect(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = c.Close(context.Background()) }()
	var create, provisioned bool
	if err = c.QueryRow(context.Background(), "select has_database_privilege(current_user,current_database(),'CREATE'),to_regclass('memcue.version') is not null and to_regclass('memcue.facts') is not null").Scan(&create, &provisioned); err != nil || create || !provisioned {
		t.Fatalf("runtime fixture preconditions: create=%t provisioned=%t err=%v", create, provisioned, err)
	}
	s, err := OpenPostgres(dsn)
	if err != nil {
		t.Fatalf("provisioned runtime role must not need DDL privilege: %v", err)
	}
	defer func() { _ = s.Close() }()
	f, err := s.AddWith("synthetic least privilege fact", "fixture", "", Meta{})
	if err != nil {
		t.Fatal(err)
	}
	got, err := s.Get(f.ID)
	if err != nil || got != f {
		t.Fatalf("runtime DML failed: %v", err)
	}
}
