package recall

import (
	"context"
	"github.com/juev/memcue/internal/store"
	"strings"
	"testing"
)

func TestTieComparatorEquivalence(t *testing.T) {
	ctx := context.Background()
	for _, a := range []string{"host:K", "host:K", "host:ſ", "host:s", "host:Ж", "host:ж", "host:�", "host:\xff", "host:"} {
		for _, b := range []string{"K", "K", "s", "ſ", "Ж", "ж", "�", "\xff", ""} {
			got, e := foldEqualContext(ctx, a, "host:", b)
			if e != nil || got != strings.EqualFold(a, "host:"+b) {
				t.Fatalf("Unicode fold differs")
			}
		}
	}
	for _, o := range []string{"repo/a x", "repo/ab x", "global x", "repo/a", "repo/a\tx", ""} {
		f := store.Fact{Origin: o}
		p := []string{"", "repo/a", "repo/b"}
		got, e := placeContext(ctx, f, p, "")
		if e != nil || got != place(f, p, "") {
			t.Fatal("place differs")
		}
	}
	for _, a := range []string{"", "a", "ab", strings.Repeat("x", 1024) + "a"} {
		for _, b := range []string{"", "a", "ab", strings.Repeat("x", 1024) + "b"} {
			x, y := store.Fact{ID: a}, store.Fact{ID: b}
			if newerContext(ctx, x, y) != newer(x, y) {
				t.Fatal("legacy ID order differs")
			}
		}
	}
}

func TestNativeTieUnicodeOrder(t *testing.T) {
	s := emptyBase(t)
	host := strings.Repeat("Ж", 8192)
	for _, scope := range []string{"host:" + strings.ToLower(host), "global", ""} {
		if _, e := s.AddWith("synthetic caddy config reload", "fixture", "", store.Meta{Scope: scope}); e != nil {
			t.Fatal(e)
		}
	}
	h, e := Search(s, Query{Text: "caddy", N: 1, Host: host, In: []string{"all"}, MinScore: MinScore})
	if e != nil || len(h) != 1 || h[0].Scope != "host:"+strings.ToLower(host) {
		t.Fatal("native Unicode tie order changed")
	}
}
