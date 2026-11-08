// Adapted from github.com/kljensen/snowball v0.10.0; see ../LICENSE.
package russian

import (
	"github.com/juev/memcue/internal/text/snowcontext/snowballword"
)

// Step 3 is the removal of the derivational suffix.
func step3(word *snowballword.SnowballWord) bool {

	// Search for a DERIVATIONAL ending in R2 (i.e. the entire
	// ending must lie in R2), and if one is found, remove it.

	suffix := word.RemoveFirstSuffixIn(word.R2start, "ост", "ость")
	return suffix != ""
}
