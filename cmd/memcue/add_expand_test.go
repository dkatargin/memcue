package main

import (
	"bytes"
	"strings"
	"testing"

	"github.com/juev/memcue/internal/extract"
)

// fakeExpandOnce answers the expansion call of add and correct with one query per fact, or fails, and counts the calls.

func withAPI(t *testing.T, url string) {
	t.Helper()
	old := extract.API.URL
	extract.API.URL = url
	t.Cleanup(func() { extract.API.URL = old })
}

func addFactForTest(t *testing.T, args ...string) string {
	t.Helper()
	var out bytes.Buffer
	if err := runAdd(args, &out); err != nil {
		t.Fatal(err)
	}
	return strings.TrimSpace(out.String())
}

// With an API endpoint, add gives the fact it stored its search queries at once (#288).
