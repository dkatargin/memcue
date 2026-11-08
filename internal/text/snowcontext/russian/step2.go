// Adapted from github.com/kljensen/snowball v0.10.0; see ../LICENSE.
package russian

import (
	"github.com/juev/memcue/internal/text/snowcontext/snowballword"
)

// Step 2 is the removal of the "и" suffix.
func step2(word *snowballword.SnowballWord) bool {
	suffix := word.RemoveFirstSuffixIn(word.RVstart, "и")
	return suffix != ""
}
