package store

import (
	"context"
	"encoding/json"
	"reflect"
	"unicode/utf8"
)

type factJSONField struct {
	name  string
	index []int
}

var factJSONFields = func() []factJSONField {
	var out []factJSONField
	var walk func(reflect.Type, []int)
	walk = func(t reflect.Type, prefix []int) {
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			idx := append(append([]int(nil), prefix...), i)
			if f.Anonymous {
				walk(f.Type, idx)
			} else {
				out = append(out, factJSONField{f.Name, idx})
			}
		}
	}
	walk(reflect.TypeFor[Fact](), nil)
	return out
}()

func marshalFact(ctx context.Context, f Fact) ([]byte, error) {
	out := []byte{'{'}
	v := reflect.ValueOf(f)
	for i, field := range factJSONFields {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		if i > 0 {
			out = append(out, ',')
		}
		key, _ := json.Marshal(field.name)
		out = append(out, key...)
		out = append(out, ':')
		value := v.FieldByIndex(field.index)
		if value.Kind() == reflect.String {
			out = append(out, '"')
			s := value.String()
			for start := 0; start < len(s); {
				if err := ctx.Err(); err != nil {
					return nil, err
				}
				end := min(start+4096, len(s))
				if end < len(s) {
					for end > start && !utf8.RuneStart(s[end]) {
						end--
					}
					if end == start {
						end = min(start+4096, len(s))
					}
				}
				b, err := json.Marshal(s[start:end])
				if err != nil {
					return nil, err
				}
				out = append(out, b[1:len(b)-1]...)
				start = end
			}
			out = append(out, '"')
		} else {
			b, err := json.Marshal(value.Interface())
			if err != nil {
				return nil, err
			}
			out = append(out, b...)
		}
	}
	out = append(out, '}')
	return out, ctx.Err()
}
