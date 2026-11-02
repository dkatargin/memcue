"""Static audit of the session card for #606: what the current binary delivers, counted by kind, source and scope.

Runs memcue session-start -part 1..3 (Claude Code) and session-card -dream-tools (Hermes) on a private copy of a text
history, for three repositories and a directory outside git. The ids come from card.log, the lines from the delivered
additionalContext, the metadata from the copy's cache after the binary opened it. Every input and output is checked
before the scratch is created. Private outputs stay under --scratch (0700/0600); stdout and --public, a new file,
carry counts and fixed category names only. No model is called. The binary runs with a fresh HOME and no global or
system git config; it is not sandboxed otherwise.
"""
import argparse
import json
import os
import random
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys

HEADER = "memcue: rules and decisions from the base"
HINT_TAIL = " more do not fit the card budget: search -in global -kind rule,decision"
STATED = ("user", "user_confirmed")
KINDS = {"rule", "decision", "pitfall", "environment", "event", "procedure", "repo", "other"}  # recall.Kinds
SOURCES = {"user", "user_confirmed", "agent", "tool", "memory"}
SCOPES = {"repo", "dir", "host", "shelf"}
METRIC = ("line_cost is the length of each fact line plus one for a newline, the same for every line; it is not the "
          "physical text, whose parts lose their final newline. delivered_chars is the physical length of the "
          "additionalContext of every part. pool is carried plus omitted plus left, from card.log.")


def fail(msg):
    sys.exit("card_audit_606: " + msg)


def write_new(path, text, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    os.fchmod(fd, mode)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def write_private(path, obj):
    write_new(path, json.dumps(obj, ensure_ascii=False, indent=1), 0o600)


def owner_only(root):
    os.chmod(root, 0o700)
    for top, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(top, n)
            st = os.lstat(p)
            if stat.S_ISDIR(st.st_mode):
                os.chmod(p, 0o700)
            elif stat.S_ISREG(st.st_mode):
                os.chmod(p, 0o600)


def card_bullets(outputs):
    """The fact lines of the card in the delivered parts, in order: the lines after the card header that start with
    "- ", without the line that counts what the budget left out."""
    out = []
    for raw in outputs:
        if not raw.strip():
            continue
        lines = json.loads(raw)["hookSpecificOutput"]["additionalContext"].split("\n")
        at = next((i for i, l in enumerate(lines) if l.startswith(HEADER)), None)
        if at is None:
            continue
        out += [l for l in lines[at + 1:] if l.startswith("- ") and not l.endswith(HINT_TAIL)]
    return out


def category(kind, scope, source):
    """A fixed name for the metadata: a value outside the allowlists is "other", never the value itself."""
    s = scope.lower()
    prefix = s.split(":", 1)[0] if ":" in s else ""
    sc = "global" if s == "global" else "none" if s == "" else prefix if prefix in SCOPES else "other"
    src = "none" if source == "" else source if source in SOURCES else "other"
    return f"{sc}:{kind if kind in KINDS else 'other'}:{src}"


def aggregate(ids, bullets, meta):
    if len(ids) != len(bullets):
        fail(f"card.log has {len(ids)} ids, the delivered card {len(bullets)} lines")
    agg = {"facts": 0, "line_cost": 0, "by": {}, "mechanical": {"facts": 0, "line_cost": 0}}
    for i, b in zip(ids, bullets):
        if i not in meta:
            fail("a carried id is not in the copy")
        kind, scope, source = meta[i]
        n = len(b) + 1
        agg["facts"] += 1
        agg["line_cost"] += n
        cell = agg["by"].setdefault(category(kind, scope, source), {"facts": 0, "line_cost": 0})
        cell["facts"] += 1
        cell["line_cost"] += n
        if source in STATED:  # mechanical source filter, not a classifier of standing behaviour
            agg["mechanical"]["facts"] += 1
            agg["mechanical"]["line_cost"] += n
    return agg


def check_public(obj, forbidden):
    text = json.dumps(obj, ensure_ascii=False)
    if "/" in text or "@" in text or any(f and f in text for f in forbidden):
        fail("public output carries an identifier or a path")


def resolve(p):
    """The absolute path of p with its parent's links resolved; p itself is not followed."""
    p = os.path.abspath(p)
    return os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))


def inside(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)


def preflight(a):
    snap = os.path.realpath(a.snapshot)
    if not os.path.isdir(snap):
        fail("snapshot missing")
    for top, dirs, files in os.walk(snap):
        for n in dirs + files:
            mode = os.lstat(os.path.join(top, n)).st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                fail("snapshot holds a link or a special file")
    binary = os.path.realpath(a.binary)
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        fail("binary is not a regular executable file")
    repos = [os.path.realpath(r) for r in a.repo]
    if len(set(repos)) != 3 or not all(os.path.isdir(os.path.join(r, ".git")) and
                                       not os.path.islink(os.path.join(r, ".git")) for r in repos):
        fail("need three distinct git clones")
    scratch = resolve(a.scratch)
    if os.path.lexists(scratch) or inside(scratch, snap) or inside(snap, scratch) or inside(binary, scratch):
        fail("scratch exists or overlaps an input: a run starts from a fresh copy")
    public = resolve(a.public) if a.public else None
    if public and (os.path.lexists(public) or not os.path.isdir(os.path.dirname(public)) or inside(public, snap)
                   or inside(public, scratch)):
        fail("public output must be a new file outside the snapshot and the scratch")
    return snap, binary, repos, scratch, public


def run(binary, env, args, payload, state):
    log = os.path.join(state, "card.log")
    before = sum(1 for _ in open(log)) if os.path.exists(log) else 0
    r = subprocess.run([binary] + args, input=json.dumps(payload), capture_output=True, text=True, env=env,
                       cwd=env["HOME"], timeout=300)
    if r.returncode != 0:
        fail(f"{args[0]} exited {r.returncode}")
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    return r.stdout, json.loads(lines[-1]) if len(lines) > before else None


def counters(rec):
    rec = rec or {}
    n = len(rec.get("facts", []))
    return {"carried": n, "omitted": rec.get("omitted", 0), "left": rec.get("left", 0),
            "excluded": rec.get("excluded", 0), "budget": rec.get("budget", 0), "used": rec.get("used", 0),
            "pool": n + rec.get("omitted", 0) + rec.get("left", 0)}


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", required=True)
    p.add_argument("--binary", required=True)
    p.add_argument("--scratch", required=True)
    p.add_argument("--repo", action="append", required=True)
    p.add_argument("--public")
    a = p.parse_args(argv)
    snap, binary, repos, scratch, public = preflight(a)
    os.makedirs(scratch, mode=0o700)
    facts, state, home = (os.path.join(scratch, d) for d in ("facts", "state", "home"))
    shutil.copytree(snap, facts, symlinks=True)
    for d in ("state", "home", "claude", "xdg", "norepo"):
        os.makedirs(os.path.join(scratch, d), mode=0o700, exist_ok=True)
    owner_only(scratch)
    env = {"PATH": os.environ["PATH"], "HOME": home, "LANG": "C.UTF-8", "MEMCUE_FACTS": facts,
           "MEMCUE_STATE_DIR": state, "CLAUDE_CONFIG_DIR": os.path.join(scratch, "claude"),
           "XDG_STATE_HOME": os.path.join(scratch, "xdg"), "XDG_CACHE_HOME": os.path.join(scratch, "xdg"),
           "XDG_CONFIG_HOME": os.path.join(scratch, "xdg"), "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": os.path.join(home, "gitconfig"),
           "MEMCUE_DREAM_BACKGROUND": "0", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
    random.SystemRandom().shuffle(repos)
    contexts = dict(zip("ABC", repos), G=os.path.join(scratch, "norepo"))
    runs = {}
    for name, cwd in contexts.items():
        payload = {"session_id": f"audit-{name}", "source": "startup", "cwd": cwd}
        outs, rec = [], None
        for part in (1, 2, 3):
            out, got = run(binary, env, ["session-start", "-part", str(part)], payload, state)
            outs.append(out)
            rec = got if part == 1 else rec
        hout, hrec = run(binary, env, ["session-card", "-dream-tools"], payload, state)
        runs[name] = {"claude": (outs, rec), "hermes": ([hout], hrec)}
    db = sqlite3.connect(f"file:{os.path.join(state, 'facts.db')}?mode=ro", uri=True)
    meta, text = {}, {}
    for i, kind, scope, source, content, created in db.execute(
            "SELECT id, kind, scope, source, content, created FROM facts f WHERE status='active' AND "
            "version=(SELECT max(version) FROM facts WHERE id=f.id)"):
        meta[i] = (kind, scope, source)
        text[i] = (content, created)
    db.close()
    public_obj, packet, private = {"metric": METRIC, "contexts": {}}, {}, {"contexts": contexts, "runs": {}}
    for name, r in runs.items():
        entry = {}
        for host, (outs, rec) in r.items():
            ids = (rec or {}).get("facts", [])
            agg = aggregate(ids, card_bullets(outs), meta)
            agg["delivered_chars"] = sum(len(json.loads(o)["hookSpecificOutput"]["additionalContext"])
                                         for o in outs if o.strip())
            agg["card_log"] = counters(rec)
            entry[host] = agg
            private["runs"][f"{name}-{host}"] = ids
            for pos, i in enumerate(ids):
                kind, scope, source = meta[i]
                item = packet.setdefault(i, {"id": i, "text": text[i][0], "created": text[i][1], "kind": kind,
                                             "scope": scope, "source": source, "cards": []})
                item["cards"].append({"context": name, "host": host, "position": pos})
        public_obj["contexts"][name] = entry
    sets = [set((runs[n]["claude"][1] or {}).get("facts", [])) for n in "ABC"]
    shared = set.intersection(*sets)
    public_obj["claude_shared_all_three"] = {"facts": len(shared),
                                             "mechanical": sum(meta[i][2] in STATED for i in shared)}
    public_obj["claude_unique_across_three"] = len(set.union(*sets))
    forbidden = (list(meta) + [v for m in meta.values() for v in m if v not in KINDS | SOURCES | {"global", ""}]
                 + [os.path.basename(r) for r in repos] + [socket.gethostname()])
    check_public(public_obj, forbidden)
    write_private(os.path.join(scratch, "private-runs.json"), private)
    write_private(os.path.join(scratch, "label-packet.json"), sorted(packet.values(), key=lambda r: r["id"]))
    owner_only(scratch)
    body = json.dumps(public_obj, indent=1, sort_keys=True) + "\n"
    if public:
        write_new(public, body, 0o644)
    print(body, end="")


if __name__ == "__main__":
    main()
