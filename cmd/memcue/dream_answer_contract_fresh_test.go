package main

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"
)

func TestDirectDreamAnswerRejectsUnsupportedFields(t *testing.T) {
	for _, extra := range []string{`,"keywords":"obsolete"`, `,"queries":["obsolete"]`, `,"future_action_property":true`} {
		t.Run(extra, func(t *testing.T) {
			env(t)
			id := addFactForTest(t, "Original actionable observation.")
			before := factHistory(t, id)
			dir, err := stateDir()
			if err != nil {
				t.Fatal(err)
			}
			p := dreamPacket{ID: "fresh-contract", Start: time.Now(), Seen: map[string]int{}, Groups: []map[string]int{{id: 1}}}
			if err := writeJSONFile(filepath.Join(dir, packetFile), p); err != nil {
				t.Fatal(err)
			}
			raw := fmt.Sprintf(`{"packet":"fresh-contract","splits":[],"actions":[{"op":"correct","id":%q,"content":"Changed actionable observation.","reason":"fixture"%s}],"scopes":[]}`, id, extra)
			path := filepath.Join(t.TempDir(), "answer.json")
			if err := os.WriteFile(path, []byte(raw), 0600); err != nil {
				t.Fatal(err)
			}
			if err := runDream([]string{"-apply", path}, &bytes.Buffer{}); err == nil {
				t.Error("direct answer silently accepted unsupported action property")
			}
			if !reflect.DeepEqual(before, factHistory(t, id)) {
				t.Error("unsupported direct answer changed fact history")
			}
		})
	}
}
