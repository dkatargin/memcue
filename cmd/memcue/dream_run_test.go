package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/juev/memcue/internal/extract"
	"github.com/juev/memcue/internal/store"
)

// fakeDreamRun plays the endpoint of dream -run: it answers the packet with the functions of the session's model in
// the tests (answerPacket) and counts the calls, which a pass makes at once (#471).
func fakeDreamRun(t *testing.T, fail error) *int {
	t.Helper()
	calls := 0
	var mu sync.Mutex
	old := dreamRunFn
	dreamRunFn = func(packet string) (extract.DreamReply, error) {
		// The fakes of the session's model behind answerPacket keep what they were sent: one answer at a time.
		mu.Lock()
		defer mu.Unlock()
		calls++
		r := extract.DreamReply{Tokens: extract.Tokens{Input: len(packet) / 4, Output: 100}}
		if fail != nil {
			return r, fail
		}
		a, err := answerPacket(packet)
		if err != nil {
			return r, err
		}
		r.Answer, err = json.Marshal(a)
		r.CostUSD, r.API, r.TTFT = 0.5, 3*time.Second, time.Second
		return r, err
	}
	t.Cleanup(func() { dreamRunFn = old })
	return &calls
}

// dreamedHoursAgo marks the base as reviewed, with ordinary query work remaining on two facts.
// The duplicate pair already has queries so the sweep can review it in a separate call.
func dreamedHoursAgo(t *testing.T, dir string) {
	t.Helper()
	fakeExpand(t, nil)
	fakeDream(t, func(string) []extract.Action { return nil })
	s, err := store.Open(factsPath())
	if err != nil {
		t.Fatal(err)
	}
	active, err := s.Active()
	if err != nil {
		t.Fatal(err)
	}
	for _, f := range active {
		if strings.Contains(f.Content, "nightly-sync") {
			if _, err := s.SetQueries(f.ID, f.Version, []string{"nightly subscriptions"}); err != nil {
				t.Fatal(err)
			}
		}
	}
	_ = s.Close()
	markPastDream(t)
}

// Without an endpoint, dream -run refuses: on Claude Code the dream stays with the session's model (#401).
func TestDreamRunNeedsAnEndpoint(t *testing.T) {
	env(t)
	calls := fakeDreamRun(t, nil)
	err := runDream([]string{"-run"}, &bytes.Buffer{})
	if !errors.Is(err, extract.ErrNoEndpoint) || *calls != 0 {
		t.Fatalf("err %v after %d calls, want ErrNoEndpoint and none", err, *calls)
	}
	if err := runDream([]string{"-run", "-since", "2026-10-01"}, &bytes.Buffer{}); err == nil {
		t.Error("-run -since was accepted")
	}
}

// A due dream is prepared, sent to the endpoint and applied: the bare facts get ordinary search queries and dream.log keeps
// the run with its tokens. The duplicate pair forms a separate review call. Right after the run nothing is due,
// so the next -run makes no call.
func TestDreamRunAppliesTheAnswer(t *testing.T) {
	dir := env(t)
	withAPI(t, "https://api.example.test")
	old, _, _, other := dreamBase(t)
	dreamedHoursAgo(t, dir)
	calls := fakeDreamRun(t, nil)

	var out bytes.Buffer
	if err := runDream([]string{"-run"}, &out); err != nil {
		t.Fatal(err)
	}
	// One call for the group of the two copies, one for the expansions.
	if *calls != 2 || !strings.Contains(out.String(), "expanded 2 facts") {
		t.Fatalf("%d calls, out %q", *calls, out.String())
	}
	for _, id := range []string{old, other} {
		if f := storedFact(t, id); len(extract.SearchQueries(f.Queries)) == 0 {
			t.Errorf("fact %s: missing ordinary queries", id)
		}
	}
	recs := readDreamLog(t, dir)
	last := recs[len(recs)-1]
	if last.Expanded != 2 || last.Tokens == nil || last.Tokens.Output != 200 || last.Error != "" || last.Packet == "" {
		t.Errorf("record %+v", last)
	}
	// The record says where the time of the pass went: the API time and the first token as the call reports them (#471).
	if tm := last.Timing; tm == nil || tm.API != 3000 || tm.TTFT != 1000 || tm.Calls != 2 || last.CostUSD != 1 {
		t.Errorf("timing %+v, cost %v", last.Timing, last.CostUSD)
	}

	out.Reset()
	if err := runDream([]string{"-run"}, &out); err != nil {
		t.Fatal(err)
	}
	if *calls != 2 || out.String() != "dream: nothing due\n" {
		t.Errorf("second run: %d calls, out %q", *calls, out.String())
	}
}

// The record of a pass keeps a line per model call (#643): its task, the work it was given, what the model proposed,
// and its tokens, cost and time, which add up to the pass's own.
func TestDreamRunLogsEachCall(t *testing.T) {
	dir := env(t)
	withAPI(t, "https://api.example.test")
	dreamBase(t)
	dreamedHoursAgo(t, dir)
	fakeDreamRun(t, nil)
	if err := runDream([]string{"-run"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	recs := readDreamLog(t, dir)
	last := recs[len(recs)-1]
	byTask := map[string]dreamCallRecord{}
	var tokens extract.Tokens
	var cost float64
	for _, c := range last.Calls {
		byTask[c.Task] = c
		tokens.Add(c.Tokens)
		cost += c.CostUSD
		if c.API != 3000 || c.Error != "" {
			t.Errorf("call %+v", c)
		}
	}
	if len(last.Calls) != 2 || tokens != *last.Tokens || cost != last.CostUSD {
		t.Fatalf("calls %+v do not add up to the pass: tokens %+v, cost %v", last.Calls, last.Tokens, last.CostUSD)
	}
	if r := byTask[taskReview]; r.Groups != 1 || r.Facts != 0 {
		t.Errorf("review call %+v, want the group of the two copies", r)
	}
	if tr := byTask[taskExpand]; tr.Facts != 2 || tr.Proposed != 2 || tr.Groups != 0 {
		t.Errorf("expand call %+v, want two facts given and two expansions", tr)
	}
}

// A failed call is logged with its error on its own line; the call that answered keeps its record.
func TestDreamRunLogsTheFailedCall(t *testing.T) {
	dir := env(t)
	withAPI(t, "https://api.example.test")
	dreamBase(t)
	dreamedHoursAgo(t, dir)
	fakeDreamRun(t, nil)
	good := dreamRunFn
	dreamRunFn = func(packet string) (extract.DreamReply, error) {
		if strings.Contains(packet, "## Группа 1") {
			return extract.DreamReply{Tokens: extract.Tokens{Input: 7}}, errModel
		}
		return good(packet)
	}
	if err := runDream([]string{"-run"}, &bytes.Buffer{}); !errors.Is(err, errModel) {
		t.Fatalf("err %v, want the call's error", err)
	}
	recs := readDreamLog(t, dir)
	last := recs[len(recs)-1]
	failed, answered := 0, 0
	for _, c := range last.Calls {
		switch {
		case c.Task == taskReview && c.Error != "" && c.Tokens.Input == 7:
			failed++
		case c.Task == taskExpand && c.Error == "" && c.Proposed == 2:
			answered++
		}
	}
	if len(last.Calls) != 2 || failed != 1 || answered != 1 {
		t.Errorf("calls %+v", last.Calls)
	}
}

// Pending queries do not make a dream due before MEMCUE_DREAM_EVERY has passed: no call.
func TestDreamRunWaitsForTheInterval(t *testing.T) {
	dir := env(t)
	withAPI(t, "https://api.example.test")
	dreamBase(t)
	fakeDream(t, func(string) []extract.Action { return nil })
	if err := dreamModel([]string{"-all"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	calls := fakeDreamRun(t, nil)
	var out bytes.Buffer
	if err := runDream([]string{"-run"}, &out); err != nil {
		t.Fatal(err)
	}
	if *calls != 0 || out.String() != "dream: nothing due\n" {
		t.Errorf("%d calls, out %q", *calls, out.String())
	}
	if recs := readDreamLog(t, dir); recs[len(recs)-1].Tokens != nil {
		t.Errorf("a run with nothing due was logged as a call: %+v", recs[len(recs)-1])
	}
}

// A failed endpoint call changes nothing and is logged with its error; the next run tries again.
func TestDreamRunLogsAFailedCall(t *testing.T) {
	dir := env(t)
	withAPI(t, "https://api.example.test")
	old, _, _, _ := dreamBase(t)
	dreamedHoursAgo(t, dir)
	calls := fakeDreamRun(t, errModel)
	if err := runDream([]string{"-run"}, &bytes.Buffer{}); !errors.Is(err, errModel) {
		t.Fatalf("err %v, want the endpoint's error", err)
	}
	if len(storedFact(t, old).Queries) > 0 {
		t.Error("a failed call wrote queries")
	}
	recs := readDreamLog(t, dir)
	if last := recs[len(recs)-1]; !strings.HasPrefix(last.Error, "model: ") || last.Tokens == nil {
		t.Errorf("record %+v", last)
	}
	failed := *calls
	fakeDreamRun(t, nil)
	if err := runDream([]string{"-run"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
	if len(storedFact(t, old).Queries) == 0 || *calls != failed {
		t.Errorf("the run after a failure did not expand (failed calls %d)", *calls)
	}
}

// fewPerPacket limits expansion to two facts per packet.
func fewPerPacket(t *testing.T) {
	t.Helper()
	old := packetExpand
	packetExpand = 2
	t.Cleanup(func() { packetExpand = old })
}

// dream -run -all finishes the base (#405): packets one after another, with no interval, until a packet has nothing
// to split or expand; that one is answered too and the loop stops. Without MEMCUE_API_URL it runs, on
// claude -p; a plain -run still refuses there.
func TestDreamRunAllFinishesTheBase(t *testing.T) {
	dir := env(t)
	ids := []string{}
	old, a, b, other := dreamBase(t)
	ids = append(ids, old, a, b, other)
	fewPerPacket(t)
	noSweep(t) // the sweep would group the duplicate pair on every pass of a base this small; see the next test
	fakeExpand(t, nil)
	fakeDream(t, func(string) []extract.Action { return nil })
	calls := fakeDreamRun(t, nil)

	var out bytes.Buffer
	if err := runDream([]string{"-run", "-all"}, &out); err != nil {
		t.Fatal(err)
	}
	if *calls < 3 || !strings.Contains(out.String(), "dream -all: done after ") {
		t.Fatalf("%d calls, out %q", *calls, out.String())
	}
	for _, id := range ids {
		f := storedFact(t, id)
		if len(extract.SearchQueries(f.Queries)) == 0 {
			t.Errorf("fact %s left with queries %q", id, f.Queries)
		}
	}
	logged := 0
	for _, r := range readDreamLog(t, dir) {
		if r.Error != "" {
			t.Errorf("record %+v", r)
		}
		if r.Timing != nil {
			logged += r.Timing.Calls
			if r.CostUSD != 0.5*float64(r.Timing.Calls) {
				t.Errorf("record of %d calls costs %v", r.Timing.Calls, r.CostUSD)
			}
		}
	}
	if logged != *calls {
		t.Errorf("the records count %d calls of %d", logged, *calls)
	}
	if err := runDream([]string{"-run"}, &bytes.Buffer{}); !errors.Is(err, extract.ErrNoEndpoint) {
		t.Errorf("plain -run without an endpoint: err %v, want ErrNoEndpoint", err)
	}
}

// A failed pass stops dream -run -all with its error; the passes before it stay applied.
func TestDreamRunAllStopsOnAFailedPass(t *testing.T) {
	dir := env(t)
	dreamBase(t)
	fewPerPacket(t)
	fakeExpand(t, nil)
	fakeDream(t, func(string) []extract.Action { return nil })
	fakeDreamRun(t, nil)
	good := dreamRunFn
	var mu sync.Mutex
	first := ""
	dreamRunFn = func(packet string) (extract.DreamReply, error) {
		// The packet of the second pass fails.
		id := regexp.MustCompile("`packet` — ровно `([^`]+)`").FindStringSubmatch(packet)[1]
		mu.Lock()
		if first == "" {
			first = id
		}
		second := id != first
		mu.Unlock()
		if second {
			return extract.DreamReply{}, errModel
		}
		return good(packet)
	}
	err := runDream([]string{"-run", "-all", "-j", "1"}, &bytes.Buffer{})
	if !errors.Is(err, errModel) || !strings.Contains(err.Error(), "pass 2") {
		t.Fatalf("err %v", err)
	}
	if recs := readDreamLog(t, dir); len(recs) != 2 || recs[0].Error != "" || recs[0].Expanded == 0 {
		t.Errorf("records %+v", recs)
	}
}

// The bound of passes stops a run that still has work and says so; the next run continues.
func TestDreamRunAllStopsAtTheBound(t *testing.T) {
	dir := env(t)
	dreamBase(t)
	fewPerPacket(t)
	fakeExpand(t, nil)
	fakeDream(t, func(string) []extract.Action { return nil })
	fakeDreamRun(t, nil)
	old := dreamAllPasses
	dreamAllPasses = 1
	t.Cleanup(func() { dreamAllPasses = old })
	err := runDream([]string{"-run", "-all", "-j", "1"}, &bytes.Buffer{})
	if n := len(readDreamLog(t, dir)); err == nil || !strings.Contains(err.Error(), "stopped after 1 passes") || n != 1 {
		t.Fatalf("err %v after %d passes", err, n)
	}
	dreamAllPasses = old
	if err := runDream([]string{"-run", "-all"}, &bytes.Buffer{}); err != nil {
		t.Fatal(err)
	}
}

// The merge sweep may keep returning the same group, but it cannot keep -all running
// after split, expansion and scope work is complete.
func TestDreamRunAllFinishesDespiteRepeatingSweep(t *testing.T) {
	dir := env(t)
	dreamBase(t)
	fewPerPacket(t)
	fakeExpand(t, nil)
	fakeDream(t, func(string) []extract.Action { return nil })
	fakeDreamRun(t, nil)
	var out bytes.Buffer
	if err := runDream([]string{"-run", "-all"}, &out); err != nil {
		t.Fatal(err)
	}
	if n := len(readDreamLog(t, dir)); !strings.Contains(out.String(),
		"dream -all: done after") || n >= dreamAllPasses {
		t.Errorf("%d passes, out %q", n, out.String())
	}
}

// -j packets of ordinary expansion work are joined in one pass. One failed call still fails the whole pass.
func TestDreamRunJoinsPackets(t *testing.T) {
	for _, tc := range []struct {
		j        string
		expanded int
		calls    int // the group of the two copies, and one call per expansion
	}{{"1", 1, 2}, {"2", 2, 3}} {
		t.Run("j"+tc.j, func(t *testing.T) {
			dir := env(t)
			withAPI(t, "https://api.example.test")
			dreamBase(t)
			dreamedHoursAgo(t, dir)
			old := packetExpand
			packetExpand = 1
			t.Cleanup(func() { packetExpand = old })
			calls := fakeDreamRun(t, nil)
			if err := runDream([]string{"-run", "-j", tc.j}, &bytes.Buffer{}); err != nil {
				t.Fatal(err)
			}
			recs := readDreamLog(t, dir)
			last := recs[len(recs)-1]
			if last.Expanded != tc.expanded || last.Timing == nil || last.Timing.Calls != tc.calls ||
				*calls != tc.calls {
				t.Errorf("expanded %d in %d calls (%+v), want %d in %d", last.Expanded, *calls, last.Timing,
					tc.expanded, tc.calls)
			}
		})
	}
}

// One failed call of a pass applies nothing of the others: the next pass asks for the same work again.
func TestDreamRunOneFailedCallAppliesNothing(t *testing.T) {
	dir := env(t)
	withAPI(t, "https://api.example.test")
	old, _, _, other := dreamBase(t)
	dreamedHoursAgo(t, dir)
	fakeDreamRun(t, nil)
	good := dreamRunFn
	dreamRunFn = func(packet string) (extract.DreamReply, error) {
		if strings.Contains(packet, "## Группа 1") {
			return extract.DreamReply{}, errModel
		}
		return good(packet)
	}
	if err := runDream([]string{"-run"}, &bytes.Buffer{}); !errors.Is(err, errModel) {
		t.Fatalf("err %v, want the call's error", err)
	}
	for _, id := range []string{old, other} {
		if len(storedFact(t, id).Queries) > 0 {
			t.Errorf("fact %s expanded by a failed pass", id)
		}
	}
}

// -j takes a count of at least one and goes with -run only.
func TestDreamRunPacketsFlag(t *testing.T) {
	env(t)
	withAPI(t, "https://api.example.test")
	for _, args := range [][]string{{"-run", "-j", "0"}, {"-prepare", "-all", "-j", "2"}} {
		if err := runDream(args, &bytes.Buffer{}); err == nil || !strings.Contains(err.Error(), "-j") {
			t.Errorf("%q: err %v", args, err)
		}
	}
}
