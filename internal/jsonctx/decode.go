package jsonctx

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

var errJSON = errors.New("invalid PostgreSQL fact JSON")

type factDecoder struct {
	strict     bool
	ctx        context.Context
	b          []byte
	i, checked int
}

func (p *factDecoder) check() error {
	if p.i-p.checked >= 256 {
		p.checked = p.i
		return p.ctx.Err()
	}
	return nil
}
func (p *factDecoder) space() error {
	// Tokens and delimiters consume bytes even when there is no whitespace.
	if e := p.check(); e != nil {
		return e
	}
	for p.i < len(p.b) {
		switch p.b[p.i] {
		case ' ', '\t', '\r', '\n':
			p.i++
			if e := p.check(); e != nil {
				return e
			}
		default:
			return nil
		}
	}
	return nil
}
func (p *factDecoder) take(c byte) bool {
	if p.i < len(p.b) && p.b[p.i] == c {
		p.i++
		return true
	}
	return false
}
func hexDigit(c byte) (uint16, bool) {
	switch {
	case c >= '0' && c <= '9':
		return uint16(c - '0'), true
	case c >= 'a' && c <= 'f':
		return uint16(c - 'a' + 10), true
	case c >= 'A' && c <= 'F':
		return uint16(c - 'A' + 10), true
	}
	return 0, false
}
func (p *factDecoder) str(want bool) (string, error) {
	if !p.take('"') {
		return "", errJSON
	}
	start := p.i
	originalStart := start
	escaped, ascii := false, true
	var out strings.Builder
	flush := func(end int) error {
		raw := make([]byte, end-start+2)
		raw[0] = '"'
		copy(raw[1:], p.b[start:end])
		raw[len(raw)-1] = '"'
		var part string
		if e := json.Unmarshal(raw, &part); e != nil {
			return errJSON
		}
		if want {
			out.WriteString(part)
		}
		start = end
		return p.ctx.Err()
	}
	for p.i < len(p.b) {
		if e := p.check(); e != nil {
			return "", e
		}
		unit := p.i
		high := false
		c := p.b[p.i]
		if c == '"' {
			if want && start == originalStart && !escaped && ascii {
				value := string(p.b[start:p.i])
				p.i++
				return value, p.ctx.Err()
			}
			if e := flush(p.i); e != nil {
				return "", e
			}
			p.i++
			return out.String(), nil
		}
		if c >= 128 {
			ascii = false
		}
		if c < 32 {
			return "", errJSON
		}
		if c == '\\' {
			escaped = true
			p.i++
			if p.i >= len(p.b) {
				return "", errJSON
			}
			escape := p.b[p.i]
			p.i++
			switch escape {
			case '"', '\\', '/', 'b', 'f', 'n', 'r', 't':
			case 'u':
				if p.i+4 > len(p.b) {
					return "", errJSON
				}
				var code uint16
				for j := 0; j < 4; j++ {
					v, ok := hexDigit(p.b[p.i+j])
					if !ok {
						return "", errJSON
					}
					code = code*16 + v
				}
				p.i += 4
				high = code >= 0xd800 && code <= 0xdbff
			default:
				return "", errJSON
			}
		} else {
			_, size := utf8.DecodeRune(p.b[p.i:])
			p.i += size
		}
		if p.i-start >= 4096 {
			end := p.i
			if high {
				end = unit
			}
			if end > start {
				if e := flush(end); e != nil {
					return "", e
				}
			}
		}
	}
	return "", errJSON
}
func (p *factDecoder) number() error {
	p.take('-')
	if p.i >= len(p.b) {
		return errJSON
	}
	if !p.take('0') {
		start := p.i
		for p.i < len(p.b) && p.b[p.i] >= '0' && p.b[p.i] <= '9' {
			p.i++
			if e := p.check(); e != nil {
				return e
			}
		}
		if start == p.i {
			return errJSON
		}
	}
	if p.take('.') {
		start := p.i
		for p.i < len(p.b) && p.b[p.i] >= '0' && p.b[p.i] <= '9' {
			p.i++
			if e := p.check(); e != nil {
				return e
			}
		}
		if start == p.i {
			return errJSON
		}
	}
	if p.take('e') || p.take('E') {
		if !p.take('+') {
			p.take('-')
		}
		start := p.i
		for p.i < len(p.b) && p.b[p.i] >= '0' && p.b[p.i] <= '9' {
			p.i++
			if e := p.check(); e != nil {
				return e
			}
		}
		if start == p.i {
			return errJSON
		}
	}
	return nil
}
func (p *factDecoder) literal(s string) bool {
	if len(p.b)-p.i >= len(s) && string(p.b[p.i:p.i+len(s)]) == s {
		p.i += len(s)
		return true
	}
	return false
}
func (p *factDecoder) skip(depth int) error {
	if depth > 10000 {
		return errJSON
	}
	if e := p.space(); e != nil {
		return e
	}

	// Depth counts the enclosing containers; a scalar at the limit is valid,
	// while another object/array would exceed encoding/json's 10000 maximum.
	if depth >= 10000 && p.i < len(p.b) && (p.b[p.i] == '{' || p.b[p.i] == '[') {
		return errJSON
	}
	if p.i >= len(p.b) {
		return errJSON
	}
	switch p.b[p.i] {
	case '"':
		_, e := p.str(false)
		return e
	case '{', '[':
		object := p.b[p.i] == '{'
		p.i++
		end := byte(']')
		if object {
			end = '}'
		}
		if e := p.space(); e != nil {
			return e
		}
		if p.take(end) {
			return nil
		}
		for {
			if object {
				if _, e := p.str(false); e != nil {
					return e
				}
				if e := p.space(); e != nil {
					return e
				}
				if !p.take(':') {
					return errJSON
				}
			}
			if e := p.skip(depth + 1); e != nil {
				return e
			}
			if e := p.space(); e != nil {
				return e
			}
			if p.take(end) {
				return nil
			}
			if !p.take(',') {
				return errJSON
			}
			if e := p.space(); e != nil {
				return e
			}
		}
	case 't':
		if p.literal("true") {
			return nil
		}
	case 'f':
		if p.literal("false") {
			return nil
		}
	case 'n':
		if p.literal("null") {
			return nil
		}
	default:
		return p.number()
	}
	return errJSON
}

type field struct {
	name  string
	index []int
	omit  bool
}

var schemas sync.Map

func fields(t reflect.Type) []field {
	if v, ok := schemas.Load(t); ok {
		return v.([]field)
	}
	var out []field
	var walk func(reflect.Type, []int)
	walk = func(t reflect.Type, prefix []int) {
		for i := 0; i < t.NumField(); i++ {
			f := t.Field(i)
			if f.PkgPath != "" {
				continue
			}
			index := append(append([]int(nil), prefix...), i)
			tag := strings.Split(f.Tag.Get("json"), ",")[0]
			if tag == "-" {
				continue
			}
			if f.Anonymous && tag == "" && f.Type.Kind() == reflect.Struct {
				walk(f.Type, index)
			} else {
				if tag == "" {
					tag = f.Name
				}
				out = append(out, field{tag, index, strings.Contains(f.Tag.Get("json"), ",omitempty")})
			}
		}
	}
	walk(t, nil)
	actual, _ := schemas.LoadOrStore(t, out)
	return actual.([]field)
}
func (p *factDecoder) value(v reflect.Value, depth int) error {
	if depth > 10000 {
		return errJSON
	}
	if e := p.space(); e != nil {
		return e
	}

	// Depth counts the enclosing containers; a scalar at the limit is valid,
	// while another object/array would exceed encoding/json's 10000 maximum.
	if depth >= 10000 && p.i < len(p.b) && (p.b[p.i] == '{' || p.b[p.i] == '[') {
		return errJSON
	}
	if e := p.ctx.Err(); e != nil {
		return e
	}
	if p.literal("null") {
		switch v.Kind() {
		case reflect.Pointer, reflect.Map, reflect.Slice, reflect.Interface:
			v.SetZero()
		}
		return nil
	}
	if v.Kind() == reflect.Pointer {
		if v.IsNil() {
			v.Set(reflect.New(v.Type().Elem()))
		}
		return p.value(v.Elem(), depth+1)
	}
	if v.Type() == reflect.TypeFor[time.Time]() {
		text, e := p.str(true)
		if e != nil {
			return e
		}
		if len(text) > 20 && (text[19] == '.' || text[19] == ',') {
			j := 20
			for j < len(text) && text[j] >= '0' && text[j] <= '9' {
				if j%256 == 0 {
					if e = p.ctx.Err(); e != nil {
						return e
					}
				}
				j++
			}
			if j > 29 {
				text = text[:29] + text[j:]
			}
		}
		if len(text) > 64 {
			return errJSON
		}
		raw, _ := json.Marshal(text)
		var t time.Time
		if e = json.Unmarshal(raw, &t); e != nil {
			return errJSON
		}
		v.Set(reflect.ValueOf(t))
		return nil
	}
	switch v.Kind() {
	case reflect.String:
		s, e := p.str(true)
		if e != nil {
			return e
		}
		v.SetString(s)
		return nil
	case reflect.Bool:
		if p.literal("true") {
			v.SetBool(true)
			return nil
		}
		if p.literal("false") {
			v.SetBool(false)
			return nil
		}
		return errJSON
	case reflect.Int, reflect.Int8, reflect.Int16, reflect.Int32, reflect.Int64:
		start := p.i
		if e := p.number(); e != nil {
			return e
		}
		if p.i-start > 20 {
			return errJSON
		}
		n, e := strconv.ParseInt(string(p.b[start:p.i]), 10, v.Type().Bits())
		if e != nil {
			return errJSON
		}
		v.SetInt(n)
		return nil
	case reflect.Uint, reflect.Uint64, reflect.Uint32:
		start := p.i
		if e := p.number(); e != nil {
			return e
		}
		if p.i-start > 20 {
			return errJSON
		}
		n, e := strconv.ParseUint(string(p.b[start:p.i]), 10, v.Type().Bits())
		if e != nil {
			return errJSON
		}
		v.SetUint(n)
		return nil
	case reflect.Struct, reflect.Map:
		if !p.take('{') {
			return errJSON
		}
		if e := p.space(); e != nil {
			return e
		}
		isMap := v.Kind() == reflect.Map
		var known []field
		if isMap {
			if v.Type().Key().Kind() != reflect.String {
				return errJSON
			}
			if v.IsNil() {
				v.Set(reflect.MakeMap(v.Type()))
			}
		} else {
			known = fields(v.Type())
		}
		if p.take('}') {
			return nil
		}
		for {
			key, e := p.str(true)
			if e != nil {
				return e
			}
			if e = p.space(); e != nil {
				return e
			}
			if !p.take(':') {
				return errJSON
			}
			var target reflect.Value
			if isMap {
				target = reflect.New(v.Type().Elem()).Elem()
			} else {
				for _, f := range known {
					if strings.EqualFold(key, f.name) {
						target = v.FieldByIndex(f.index)
						break
					}
				}
			}
			if !target.IsValid() {
				if p.strict {
					return errJSON
				}
				if e = p.skip(depth + 1); e != nil {
					return e
				}
			} else {
				if e = p.value(target, depth+1); e != nil {
					return e
				}
				if isMap {
					v.SetMapIndex(reflect.ValueOf(key).Convert(v.Type().Key()), target)
				}
			}
			if e = p.space(); e != nil {
				return e
			}
			if p.take('}') {
				return nil
			}
			if !p.take(',') {
				return errJSON
			}
			if e = p.space(); e != nil {
				return e
			}
		}
	case reflect.Slice:
		if !p.take('[') {
			return errJSON
		}
		v.Set(reflect.MakeSlice(v.Type(), 0, 0))
		if e := p.space(); e != nil {
			return e
		}
		if p.take(']') {
			return nil
		}
		for {
			elem := reflect.New(v.Type().Elem()).Elem()
			if e := p.value(elem, depth+1); e != nil {
				return e
			}
			v.Set(reflect.Append(v, elem))
			if e := p.space(); e != nil {
				return e
			}
			if p.take(']') {
				return nil
			}
			if !p.take(',') {
				return errJSON
			}
		}
	}
	return errJSON
}

// Unmarshal covers the concrete scalar/struct/map/slice wire types used by
// Memcue. It rejects unsupported Go destinations; unknown JSON fields are
// validated and skipped without materializing them. No accepted Fact cap changes.
func Unmarshal(ctx context.Context, b []byte, target any, strict ...bool) error {
	v := reflect.ValueOf(target)
	if v.Kind() != reflect.Pointer || v.IsNil() {
		return errJSON
	}
	if e := ctx.Err(); e != nil {
		return e
	}
	p := factDecoder{ctx: ctx, b: b, strict: len(strict) > 0 && strict[0]}
	if e := p.value(v.Elem(), 0); e != nil {
		return e
	}
	if e := p.space(); e != nil {
		return e
	}
	if p.i != len(b) {
		return errJSON
	}
	return ctx.Err()
}
