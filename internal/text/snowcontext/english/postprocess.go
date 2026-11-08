// Adapted from github.com/kljensen/snowball v0.10.0; see ../LICENSE.
package english

import (
	"github.com/juev/memcue/internal/text/snowcontext/snowballword"
)

// Applies transformations necessary after
// a word has been completely processed.
func postprocess(word *snowballword.SnowballWord) {

	uncapitalizeYs(word)
}
