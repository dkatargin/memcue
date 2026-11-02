#!/bin/sh
# One Claude Code run of the #601 stand, inside its container: agent601.sh capture|probe.
# /stand is the run directory run601.py prepared: ws/ (a git repository), turn1.txt and turn2.txt or probe.txt,
# base/ (empty, or the facts a capture run left). The plugin of the arm is at /opt/p601/plugin, memcue at
# /usr/local/bin/memcue, both read-only. Home, config, caches and temporary files live under /stand; records go to
# /stand/rec. The model is the alias in STAND601_MODEL (default sonnet).
set -u
mode=$1
R=/stand
for v in $(env | sed -n 's/^\(MEMCUE_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
export HOME=$R/home CLAUDE_CONFIG_DIR=$R/home/.claude XDG_CONFIG_HOME=$R/home/.config \
	XDG_DATA_HOME=$R/home/.local/share XDG_STATE_HOME=$R/home/.local/state XDG_CACHE_HOME=$R/home/.cache \
	TMPDIR=$R/tmp MEMCUE_FACTS=$R/base/facts MEMCUE_STATE_DIR=$R/state MEMCUE_BIN=/usr/local/bin/memcue \
	MEMCUE_AUTO_INSTALL=0 MEMCUE_DREAM_BACKGROUND=0 STAND601_HOOK_LOG=$R/rec/hook601.log \
	DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1 CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
	CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
model=${STAND601_MODEL:-sonnet}
# No web, and none of the tools that reach past the container (cloud routines, schedules, workflows, notifications).
denied=WebFetch,WebSearch,RemoteTrigger,CronCreate,CronDelete,ScheduleWakeup,Workflow,PushNotification
mkdir -p "$HOME" "$CLAUDE_CONFIG_DIR" "$TMPDIR" "$R/rec" "$R/state"

snap() { # snap NAME: a copy of the text history as it is now
	mkdir -p "$R/rec/base-$1"
	if [ -d "$R/base/facts" ]; then cp -r "$R/base/facts" "$R/rec/base-$1/facts"; fi
}

# What the hooks of this plugin hand the model, run once before the session with a state directory of their own, so
# the session's own start is not changed by it: the first line of each part's output, and its length.
preflight() {
	python3 -I - "$1" > "$R/rec/preflight.json" 2> "$R/rec/preflight.err" <<'EOF'
import json, os, subprocess, sys
hooks = json.load(open("/opt/p601/plugin/hooks/hooks.json"))["hooks"]["SessionStart"]
env = dict(os.environ, CLAUDE_PLUGIN_ROOT="/opt/p601/plugin", MEMCUE_STATE_DIR="/stand/preflight-state",
           STAND601_HOOK_LOG="/stand/rec/preflight-hook601.log")
payload = json.dumps({"session_id": "preflight", "source": "startup", "cwd": sys.argv[1]})
out = []
for h in hooks:
    cmd = h["hooks"][0]["command"].replace("${CLAUDE_PLUGIN_ROOT}", "/opt/p601/plugin")
    p = subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True, text=True, env=env, cwd=sys.argv[1])
    try:
        ctx = json.loads(p.stdout)["hookSpecificOutput"]["additionalContext"] if p.stdout.strip() else ""
    except ValueError:
        ctx = None
    out.append({"command": h["hooks"][0]["command"], "exit": p.returncode, "chars": None if ctx is None else len(ctx),
                "context": ctx})
print(json.dumps(out, ensure_ascii=False))
EOF
}

# run_claude PROMPT [EXTRA FLAGS...]: one claude -p call with the flags every run shares.
run_claude() {
	prompt=$1
	shift
	claude -p "$prompt" --output-format stream-json --verbose --include-hook-events --model "$model" \
		--permission-mode bypassPermissions --setting-sources "" --strict-mcp-config \
		--mcp-config '{"mcpServers":{}}' --plugin-dir /opt/p601/plugin --disallowedTools "$denied" \
		--max-budget-usd "${STAND601_MAX_USD:-0.60}" "$@" < /dev/null
}

cd "$R/ws" || exit 1
claude --version > "$R/rec/claude-version.txt" 2>&1
sha256sum /usr/local/bin/memcue /opt/p601/plugin/hooks/hooks.json > "$R/rec/inputs.sha256" 2>&1
preflight "$R/ws"
snap before
status=0
if [ "$mode" = capture ]; then
	run_claude "$(cat "$R/turn1.txt")" > "$R/rec/turn1.jsonl" 2> "$R/rec/turn1.err" || status=$?
	echo "$status" > "$R/rec/turn1.exit"
	snap after1
	sid=$(python3 -I -c 'import json,sys
for l in open(sys.argv[1]):
    try: e = json.loads(l)
    except ValueError: continue
    if e.get("type") == "system" and e.get("subtype") == "init": print(e.get("session_id") or ""); break' \
		"$R/rec/turn1.jsonl" 2>/dev/null)
	if [ "$status" = 0 ] && [ -n "$sid" ]; then
		s2=0
		run_claude "$(cat "$R/turn2.txt")" --resume "$sid" > "$R/rec/turn2.jsonl" 2> "$R/rec/turn2.err" || s2=$?
		echo "$s2" > "$R/rec/turn2.exit"
		[ "$s2" = 0 ] || status=$s2
	else
		[ "$status" = 0 ] && status=97 # no session id to resume
	fi
	snap after2
else
	run_claude "$(cat "$R/probe.txt")" --no-session-persistence > "$R/rec/probe.jsonl" 2> "$R/rec/probe.err" ||
		status=$?
	snap after
fi
[ -f "$R/state/card.log" ] && cp "$R/state/card.log" "$R/rec/card.log"
echo "$status" > "$R/rec/exit"
