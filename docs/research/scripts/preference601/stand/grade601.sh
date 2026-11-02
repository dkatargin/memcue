#!/bin/sh
# One grading call of the #601 stand, inside its container: grade601.sh. /stand holds prompt.txt (the grading
# instructions with one record, no arm) and model (the alias). The grader has no tools, no plugin and no MCP server;
# its answer goes to /stand/out.json.
set -u
R=/stand
for v in $(env | sed -n 's/^\(MEMCUE_[A-Z_]*\)=.*/\1/p'); do unset "$v"; done
export HOME=$R/home CLAUDE_CONFIG_DIR=$R/home/.claude XDG_CONFIG_HOME=$R/home/.config \
	XDG_DATA_HOME=$R/home/.local/share XDG_STATE_HOME=$R/home/.local/state XDG_CACHE_HOME=$R/home/.cache \
	TMPDIR=$R/tmp DISABLE_TELEMETRY=1 DISABLE_ERROR_REPORTING=1 DISABLE_AUTOUPDATER=1 \
	CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
mkdir -p "$CLAUDE_CONFIG_DIR" "$TMPDIR"
cd "$R" || exit 1
status=0
claude -p --output-format json --model "$(cat "$R/model")" --tools "" --setting-sources "" --strict-mcp-config \
	--mcp-config '{"mcpServers":{}}' --no-session-persistence --disable-slash-commands --max-budget-usd 0.50 \
	< "$R/prompt.txt" > "$R/out.json" 2> "$R/err.log" || status=$?
echo "$status" > "$R/exit"
