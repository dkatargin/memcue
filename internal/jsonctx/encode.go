package jsonctx

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"reflect"
	"sort"
	"unicode/utf8"
)

type encodeStopped struct{ err error }

func Marshal(ctx context.Context, value any, escape ...bool) (out []byte, err error) {
	escapeHTML := len(escape) == 0 || escape[0]
	defer func() {
		if v := recover(); v != nil {
			if s, ok := v.(encodeStopped); ok {
				out = nil
				err = s.err
			} else {
				panic(v)
			}
		}
	}()
	var encode func(reflect.Value, int) error
	stringValue := func(s string) error {
		out = append(out, '"')
		for i := 0; i < len(s); {
			if e := ctx.Err(); e != nil {
				return e
			}
			end := min(i+4096, len(s))
			if end < len(s) {
				for end > i && !utf8.RuneStart(s[end]) {
					end--
				}
				if end == i {
					end = min(i+4096, len(s))
				}
			}
			var b []byte
			var e error
			if escapeHTML {
				b, e = json.Marshal(s[i:end])
			} else {
				var buf bytes.Buffer
				enc := json.NewEncoder(&buf)
				enc.SetEscapeHTML(false)
				e = enc.Encode(s[i:end])
				raw := buf.Bytes()
				if len(raw) > 0 {
					b = raw[:len(raw)-1]
				}
			}
			if e != nil {
				return e
			}
			out = append(out, b[1:len(b)-1]...)
			i = end
		}
		out = append(out, '"')
		return ctx.Err()
	}
	empty := func(v reflect.Value) bool {
		switch v.Kind() {
		case reflect.Array, reflect.Map, reflect.Slice, reflect.String:
			return v.Len() == 0
		case reflect.Bool, reflect.Int, reflect.Int64, reflect.Uint, reflect.Float32, reflect.Float64, reflect.Interface, reflect.Pointer:
			return v.IsZero()
		}
		return false
	}
	encode = func(v reflect.Value, depth int) error {
		if e := ctx.Err(); e != nil {
			return e
		}
		if depth > 10000 {
			return errJSON
		}
		if !v.IsValid() {
			out = append(out, "null"...)
			return nil
		}
		if v.Kind() == reflect.Interface {
			if v.IsNil() {
				out = append(out, "null"...)
				return nil
			}
			return encode(v.Elem(), depth+1)
		}
		if v.Kind() == reflect.Pointer {
			if v.IsNil() {
				out = append(out, "null"...)
				return nil
			}
			return encode(v.Elem(), depth+1)
		}
		if v.CanInterface() {
			if _, ok := v.Interface().(json.Marshaler); ok {
				var buf bytes.Buffer
				enc := json.NewEncoder(&buf)
				enc.SetEscapeHTML(escapeHTML)
				e := enc.Encode(v.Interface())
				b := buf.Bytes()
				if len(b) > 0 {
					b = b[:len(b)-1]
				}
				if e != nil {
					return e
				}
				out = append(out, b...)
				return ctx.Err()
			}
		}
		switch v.Kind() {
		case reflect.String:
			return stringValue(v.String())
		case reflect.Struct:
			out = append(out, '{')
			n := 0
			for _, f := range fields(v.Type()) {
				item := v.FieldByIndex(f.index)
				if f.omit && empty(item) {
					continue
				}
				if n > 0 {
					out = append(out, ',')
				}
				n++
				if e := stringValue(f.name); e != nil {
					return e
				}
				out = append(out, ':')
				if e := encode(item, depth+1); e != nil {
					return e
				}
			}
			out = append(out, '}')
		case reflect.Map:
			if v.IsNil() {
				out = append(out, "null"...)
				return nil
			}
			keys := v.MapKeys()
			sort.Slice(keys, func(i, j int) bool {
				if e := ctx.Err(); e != nil {
					panic(encodeStopped{e})
				}
				return keys[i].String() < keys[j].String()
			})
			out = append(out, '{')
			for i, k := range keys {
				if k.Kind() != reflect.String {
					return errJSON
				}
				if i > 0 {
					out = append(out, ',')
				}
				if e := stringValue(k.String()); e != nil {
					return e
				}
				out = append(out, ':')
				if e := encode(v.MapIndex(k), depth+1); e != nil {
					return e
				}
			}
			out = append(out, '}')
		case reflect.Array, reflect.Slice:
			if v.Kind() == reflect.Slice && v.IsNil() {
				out = append(out, "null"...)
				return nil
			}
			if v.Type().Elem().Kind() == reflect.Uint8 && v.Kind() == reflect.Slice {
				out = append(out, '"')
				b := v.Bytes()
				for start := 0; start < len(b); {
					if e := ctx.Err(); e != nil {
						return e
					}
					end := min(start+3072, len(b))
					part := base64.StdEncoding.EncodeToString(b[start:end])
					out = append(out, part...)
					start = end
				}
				out = append(out, '"')
				return ctx.Err()
			}
			out = append(out, '[')
			for i := 0; i < v.Len(); i++ {
				if i > 0 {
					out = append(out, ',')
				}
				if e := encode(v.Index(i), depth+1); e != nil {
					return e
				}
			}
			out = append(out, ']')
		default:
			b, e := json.Marshal(v.Interface())
			if e != nil {
				return e
			}
			out = append(out, b...)
		}
		return ctx.Err()
	}
	err = encode(reflect.ValueOf(value), 0)
	if err != nil {
		return nil, err
	}
	return out, ctx.Err()
}
