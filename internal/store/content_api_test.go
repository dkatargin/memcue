package store

import (
	"reflect"
	"testing"
)

func TestContentOnlyCurrentModels(t *testing.T) {
	for _, model := range []any{Fact{}, FactInput{}} {
		typ := reflect.TypeOf(model)
		for _, name := range []string{"Keywords", "Queries"} {
			if _, ok := typ.FieldByName(name); ok {
				t.Errorf("%s still exposes obsolete field %s", typ.Name(), name)
			}
		}
	}
	s, _ := open(t)
	cols, err := factColumns(s.db)
	if err != nil {
		t.Fatal(err)
	}
	if cols["keywords"] || cols["queries"] {
		t.Error("fresh facts schema contains auxiliary columns")
	}

}
