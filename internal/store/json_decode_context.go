package store

import (
	"context"
	"github.com/juev/memcue/internal/jsonctx"
)

func unmarshalFact(ctx context.Context, b []byte, f *Fact) error { return jsonctx.Unmarshal(ctx, b, f) }
