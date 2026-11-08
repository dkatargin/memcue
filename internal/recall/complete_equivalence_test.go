package recall

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"math/rand"
	"reflect"
	"strings"
	"testing"

	"github.com/juev/memcue/internal/text"
)

func TestCompleteModelEquivalence(t *testing.T) {
	rng := rand.New(rand.NewSource(680681))
	alphabet := []rune("abcXYZ0123ткжё_ \n\t\u00a0\u2003!#-\ufffd")
	for i := 0; i < 1500; i++ {
		var b strings.Builder
		for j := 0; j < rng.Intn(300); j++ {
			b.WriteRune(alphabet[rng.Intn(len(alphabet))])
		}
		v := b.String()
		if i%20 == 0 {
			v = "tk" + strings.Repeat("a", 512) + "123"
		}
		ticket, e := text.IsTicketContext(context.Background(), v)
		if e != nil || ticket != text.IsTicket(v) {
			t.Fatal("ticket baseline changed")
		}
		number, e := text.IsNumberTermContext(context.Background(), v)
		if e != nil || number != text.IsNumberTerm(v) {
			t.Fatal("number baseline changed")
		}
		if IsMessage(Query{Text: v}) != (len(strings.Fields(v)) > messageWords) {
			t.Fatal("Unicode message baseline changed")
		}
		for _, st := range []string{v, v + "suffix", strings.TrimSuffix(v, "3"), "перезагрузка"} {
			covered, e := text.CoversContext(context.Background(), v, st)
			if e != nil || covered != text.Covers(v, st) {
				t.Fatal("prefix/equality baseline changed")
			}
		}
	}
	s := setup(t)
	// Native Search/Recall output is compared across the supplied candidate baseline
	// and the repaired source by an exact-source overlay run, not a copied model.
	var results []any
	for _, q := range []string{"caddy config", "перезагрузка конфиг", "PROJ-1234", "порт 6432", "caddy public reload config path words more message sentence", "kafka zookeeper", "JAVA_HOME openjdk"} {
		for _, floor := range []float64{0, MinScore, MessageFloor} {
			hits, e := Search(s, Query{Text: q, N: 10, MinScore: floor})
			if e != nil {
				t.Fatal(e)
			}
			var rows []string
			for _, h := range hits {
				rows = append(rows, fmt.Sprintf("%s|%.17g", h.Content, h.BM25))
			}
			results = append(results, rows)
		}
		p := Params{Candidates: 80, MinTerms: 1, MinMatched: 1, MinCoverage: .85, MinContained: .8}
		hits, e := Recall(s, q, p)
		if e != nil {
			t.Fatal(e)
		}
		var rows []string
		for _, h := range hits {
			rows = append(rows, fmt.Sprintf("%s|%.17g|%d|%.17g", h.Content, h.Coverage, h.Matched, h.bm25))
		}
		results = append(results, rows)
		again, e := Recall(s, q, p)
		if e != nil || !reflect.DeepEqual(hits, again) {
			t.Fatal("unstable recall")
		}
	}
	raw, e := json.Marshal(results)
	if e != nil {
		t.Fatal(e)
	}
	t.Logf("native-equivalence-sha256=%x", sha256.Sum256(raw))
}
