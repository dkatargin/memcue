// Adapted from github.com/kljensen/snowball v0.10.0; see ../LICENSE.
package russian

import (
	"github.com/juev/memcue/internal/text/snowcontext/snowballword"
)

func preprocess(word *snowballword.SnowballWord) {

	r1start, r2start, rvstart := findRegions(word)
	word.R1start = r1start
	word.R2start = r2start
	word.RVstart = rvstart

}
