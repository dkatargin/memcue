package extract

import (
	"strings"
	"testing"
)

func TestDreamSystemNamesActualAnswerHeading(t *testing.T) {
	const heading = "Answer format"
	if !strings.Contains(DreamInstructions("fixture"), "## "+heading) {
		t.Fatal("fixture packet has no answer heading")
	}
	if !strings.Contains(dreamRunSystem, heading) {
		t.Fatal("active system prompt names an obsolete answer heading")
	}
}
