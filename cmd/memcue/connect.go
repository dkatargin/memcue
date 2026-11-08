package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strconv"
	"syscall"

	"github.com/juev/memcue/internal/store"
	"github.com/juev/memcue/internal/tailnet"
)

func runConnect(args []string, out io.Writer) error {
	if len(args) == 0 {
		return errors.New("usage: memcue connect status|serve [-bootstrap]|login|off")
	}
	mode, err := tailnet.Mode()
	if err != nil {
		return err
	}
	dir, err := tailnet.StateDir()
	if err != nil {
		return err
	}
	cfg := tailnet.Config{Dir: dir}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if args[0] == "status" && len(args) == 1 {
		state := tailnet.State{State: "Stopped"}
		if _, err := os.Lstat(dir); err == nil {
			got, requestErr := tailnet.Admin(ctx, cfg, "status")
			if requestErr == nil {
				state = got
			} else {
				state.State = "Unavailable"
			}
		} else if !os.IsNotExist(err) {
			return errors.New("cannot inspect private tailnet state directory")
		}
		return json.NewEncoder(out).Encode(struct {
			Mode string `json:"mode"`
			tailnet.State
		}{mode, state})
	}
	if args[0] == "off" && len(args) == 1 {
		state, err := tailnet.Admin(ctx, cfg, "off")
		if err != nil {
			return err
		}
		return json.NewEncoder(out).Encode(state)
	}
	if mode != "embedded" {
		return errors.New("enable embedded transport explicitly: export MEMCUE_TAILSCALE_MODE=embedded")
	}
	dsn := os.Getenv("MEMCUE_POSTGRES_DSN")
	if dsn == "" {
		return errors.New("connect requires an explicit MEMCUE_POSTGRES_DSN backend")
	}
	pg, err := store.PostgresConfig(dsn)
	if err != nil {
		return err
	}
	cfg, err = tailnet.Settings(pg.Host, strconv.Itoa(int(pg.Port)))
	if err != nil {
		return err
	}
	switch args[0] {
	case "serve":
		fs := flag.NewFlagSet("connect serve", flag.ContinueOnError)
		bootstrap := fs.Bool("bootstrap", false, "explicitly bootstrap from MEMCUE_TAILSCALE_AUTH_KEY_FILE")
		if err := fs.Parse(args[1:]); err != nil {
			return err
		}
		if fs.NArg() != 0 {
			return errors.New("connect serve accepts only -bootstrap")
		}
		return tailnet.Run(ctx, cfg, *bootstrap, make(chan struct{}))
	case "login":
		if len(args) != 1 {
			return errors.New("usage: memcue connect login")
		}
		state, err := tailnet.Admin(ctx, cfg, "login")
		if err != nil {
			return err
		}
		if state.AuthURL != "" {
			_, err = fmt.Fprintln(out, "Open this URL to authorize the Memcue node:\n"+state.AuthURL)
			return err
		}
		_, err = fmt.Fprintln(out, "Node authorization state: "+state.State)
		return err
	default:
		return errors.New("usage: memcue connect status|serve [-bootstrap]|login|off")
	}
}
