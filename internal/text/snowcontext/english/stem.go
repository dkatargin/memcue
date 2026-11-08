// Adapted from github.com/kljensen/snowball v0.10.0; see ../LICENSE.
package english

import (
	"context"
	"github.com/juev/memcue/internal/text/snowcontext/snowballword"
)

// Stem an English word.  This is the only exported
// function in this package.
func stem(ctx context.Context, word string, stemStopwWords bool) string {

	word = snowballword.Normalize(ctx, word)

	// Return small words and stop words
	if len(word) <= 2 || (!stemStopwWords && IsStopWord(word)) {
		return word
	}

	// Return special words immediately
	if specialVersion := stemSpecialWord(word); specialVersion != "" {
		word = specialVersion
		return word
	}

	w := snowballword.New(word, ctx)

	// Stem the word.  Note, each of these
	// steps will alter `w` in place.
	//
	preprocess(w)
	step0(w)
	step1a(w)
	step1b(w)
	step1c(w)
	step2(w)
	step3(w)
	step4(w)
	step5(w)
	postprocess(w)

	return w.String()

}

func Stem(ctx context.Context, word string, stop bool) (result string, err error) {
	defer snowballword.Recover(&err)
	result = stem(ctx, word, stop)
	return
}
