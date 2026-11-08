// Adapted from github.com/kljensen/snowball v0.10.0; see ../LICENSE.
package russian

import (
	"context"
	"github.com/juev/memcue/internal/text/snowcontext/snowballword"
)

// Stem an Russian word.  This is the only exported
// function in this package.
func stem(ctx context.Context, word string, stemStopwWords bool) string {

	word = snowballword.Normalize(ctx, word)
	w := snowballword.New(word, ctx)

	// Return small words and stop words
	if len(w.RS) <= 2 || (!stemStopwWords && IsStopWord(word)) {
		return word
	}

	preprocess(w)
	step1(w)
	step2(w)
	step3(w)
	step4(w)
	return w.String()

}

func Stem(ctx context.Context, word string, stop bool) (result string, err error) {
	defer snowballword.Recover(&err)
	result = stem(ctx, word, stop)
	return
}
