package main

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/juev/memcue/internal/extract"
	"github.com/juev/memcue/internal/store"
)

// fakeTranslate answers every translation with "translated <id>" and records the ids it got.
func fakeTranslate(t *testing.T) *[]string {
	t.Helper()
	var sent []string
	old := translateFn
	translateFn = func(input string) ([]extract.Translated, error) {
		var req struct {
			Facts []struct{ ID, Text string } `json:"facts"`
		}
		if err := json.Unmarshal([]byte(input), &req); err != nil {
			return nil, err
		}
		var r []extract.Translated
		for _, f := range req.Facts {
			sent = append(sent, f.ID)
			r = append(r, extract.Translated{ID: f.ID, Translation: "translated " + f.ID})
		}
		return r, nil
	}
	t.Cleanup(func() { translateFn = old })
	return &sent
}

// translateBase stores three unrelated facts that already have search queries; the last one has its translation too.
func translateBase(t *testing.T) (first, second, done string) {
	t.Helper()
	s, err := store.Open(factsPath())
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = s.Close() }()
	add := func(c string, q ...string) string {
		f, err := s.AddWith(c, nil, "x 2026-10-19", "", store.Meta{})
		if err != nil {
			t.Fatal(err)
		}
		if _, err := s.SetQueries(f.ID, f.Version, q); err != nil {
			t.Fatal(err)
		}
		time.Sleep(2 * time.Millisecond) // a ULID orders by millisecond only
		return f.ID
	}
	first = add("Postgres демо-базы слушает порт 5432 на db1.", "база данных")
	second = add("Gradle в demo-app требует JAVA_HOME=/opt/jdk-21.", "сборка")
	done = add("Caddy проксирует vault.example.org.", "прокси", extract.TranslationPrefix+"Caddy proxies vault.example.org.")
	return
}
