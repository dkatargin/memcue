"""Count, with no model call, how often a Read touches a file that a memcue fact names (#598).

The first stage of #598: before any A/B with a model, how many facts name a file in a form a Read could be matched
against, and how many real Read calls touch such a file at a time the fact was in force. Experiment only, not part of
memcue; it reads copies and writes only under --out.

    python3 -I file598.py measure --facts FACTS_DIR [--claude-projects DIR] [--hermes-state STATE_DB] \\
        --home HOME --host HOST --today YYYY-MM-DD [--tz-minutes N] [--snapshot-time ISO] [--claude-dir DIR] \\
        [--exclude-session ID ...] [--stand-marker TEXT ...] --out NEW_DIR
    python3 -I file598.py summarize --in MEASURE_DIR --out NEW_DIR

measure writes facts.jsonl and calls.jsonl (one line per fact and per call, with paths and fact IDs: keep them out
of any repository), meta.json and summary.json (counts, dates and timings; no host, path, session or fact ID).
Every file is created 0600 in a 0700 directory, whatever the umask. summarize recomputes summary.json from the first
three, so a summary can be checked against the raw lines. A named input that is missing, of the wrong type or a fact
history that store.ParseFacts would refuse stops the run before the output directory is made.

A path is taken from a fact's text only when its shape is unambiguous (see extract_paths). A call matches a fact
strongly when the path it reads is the fact's absolute path, its ~/ path under --home, the fact's absolute path moved
to another worktree of the same repository, or its repository-relative path under the root of a checkout of the
fact's project; the project of a checkout comes from its git remotes, as memcue's tier.Keys reads them (without
insteadOf and include). A directory prefix, a bare file name and a relative path under another root are counted as
loose matches only.

Time is approximate. A version's created time is the time of its write only for Add, Correct, Retire, Restore and
SplitFact; Relabel, Retag and SetQueries copy the time of the version before, so when a scope, origin or expiry
changed is unknown. "asof" counts a match only when every version that may have been in force at the call matches;
a match that depends on such a change is "ambiguous" and counted apart. --snapshot-time, when the copy was taken,
settles every version for calls after it. "today" is the same judgement at the end of --today in --tz-minutes,
ignoring when the call was made: an upper bound, not a past chance. The remotes of a checkout are read as they are
now, not as they were.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The first directory of an absolute path a fact may name. Anything else (/api/v1/users, /review) is an endpoint or a
# command more often than a file.
ROOTS = {"home", "Users", "opt", "etc", "usr", "var", "tmp", "srv", "root", "mnt", "media", "private", "Library",
         "Applications", "System", "Volumes", "nix", "run", "lib", "bin", "sbin", "snap", "proc", "sys", "dev",
         "boot"}
EXT = set("""go mod sum work py pyi ipynb js mjs cjs ts tsx jsx json jsonl json5 yaml yml toml md mdx txt rst adoc sh
bash zsh fish ps1 bat rs c h cc cpp hpp java kt kts gradle swift rb php sql sqlite db conf cfg ini env lock xml html
htm css scss sass less proto plist service timer socket log csv tsv lua vim el nix tf hcl tmpl tpl gotmpl j2
properties pem crt pub patch diff dart scala clj ex exs erl hs zig svelte vue astro graphql gql pbxproj xcconfig
entitlements storyboard xib desktop rules cmake mk typ tex bib pdf png jpg jpeg gif svg webp kdl""".split())
NAMES = {"Makefile", "GNUmakefile", "Dockerfile", "Containerfile", "Justfile", "justfile", "Caddyfile", "Procfile",
         "Gemfile", "Rakefile", "Vagrantfile", "Jenkinsfile", "Brewfile", "LICENSE", "CODEOWNERS"}
DOTFILES = {".gitignore", ".gitattributes", ".gitmodules", ".gitconfig", ".editorconfig", ".env", ".envrc", ".zshrc",
            ".zprofile", ".zshenv", ".bashrc", ".bash_profile", ".profile", ".inputrc", ".vimrc", ".npmrc", ".netrc",
            ".dockerignore", ".tool-versions", ".nvmrc", ".python-version"}
# Product names shaped like a file name.
PRODUCTS = {"node.js", "vue.js", "next.js", "nuxt.js", "three.js", "d3.js", "chart.js", "express.js", "ember.js",
            "backbone.js", "socket.io"}

URL = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S*")
SCP = re.compile(r"[\w.-]+@[\w.-]+:\S*")
# A token keeps $ { } * ? so that a variable or a glob taints the whole token and drops it.
TOKEN = re.compile(r"[A-Za-z0-9_.@+~/${}*?-]+")
HOSTLIKE = re.compile(r"^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
QUOTED = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|`[^`\n]*`")
TEMP_ROOTS = ("/tmp", "/var/tmp")
STRONG = ("abs", "home", "abs_worktree", "rel")


def filelike(name: str) -> bool:
    if name in NAMES:
        return True
    if name.startswith("."):
        return name in DOTFILES
    stem, dot, ext = name.rpartition(".")
    return bool(dot and stem) and ext.lower() in EXT


def hostlike(name: str) -> bool:
    return bool(HOSTLIKE.match(name)) and name.rpartition(".")[2].isalpha()


def classify(tok: str) -> tuple[str, str] | None:
    if any(c in tok for c in "${}*?") or "//" in tok:
        return None
    tok = tok.rstrip(".")
    is_dir = tok.endswith("/")
    tok = tok.rstrip("/")
    if not tok:
        return None
    if tok.startswith("~"):
        rest = tok[2:] if tok.startswith("~/") else ""
        comps = rest.split("/")
        if not rest or any(c in ("", ".", "..") for c in comps):
            return None
        return ("home" if filelike(comps[-1]) and not is_dir else "homedir"), tok
    if tok.startswith("/"):
        comps = tok[1:].split("/")
        if len(comps) < 2 or comps[0] not in ROOTS or any(c in ("", ".", "..") for c in comps):
            return None
        return ("abs" if filelike(comps[-1]) and not is_dir else "absdir"), tok
    if tok.startswith("./"):
        tok = tok[2:]
    comps = tok.split("/")
    if any(c in ("", ".", "..") for c in comps) or is_dir or not filelike(comps[-1]):
        return None
    if len(comps) >= 2:
        return None if hostlike(comps[0]) else ("rel", tok)
    return None if tok.lower() in PRODUCTS else ("base", tok)


def extract_paths(text: str) -> list[tuple[str, str]]:
    """The paths a text names, each once, in text order: (kind, path), kind one of abs, absdir, home, homedir, rel,
    base. URLs and scp-style remotes are cut out first; a token with a variable or a glob is dropped."""
    text = SCP.sub(" ", URL.sub(" ", text or ""))
    spaced = [(q.start(), q.end()) for q in QUOTED.finditer(text) if any(c.isspace() for c in q.group(0))]
    out: list[tuple[str, str]] = []
    for m in TOKEN.finditer(text):
        p = classify(m.group(0))
        if not p or p in out:
            continue
        s, e = m.start(), m.end()
        # A bracket or a backslash next to the token cuts a name in two (a[12].conf, my\ file.conf); a path followed
        # by a space inside quotes is the head of a spaced name ("foo bar.conf", "foo.conf backup"). Neither is a
        # path. A bare name is never a strong match and is left alone.
        if text[e:e + 1] in ("[", "]", "\\") or text[s - 1:s] in ("[", "]", "\\"):
            continue
        if p[0] != "base" and text[e:e + 1].isspace() and any(a < s and e < b for a, b in spaced):
            continue
        out.append(p)
    return out


def normalize_remote(url: str) -> str:
    """tier.Normalize: host/path of a remote URL, lowercased, without scheme, user, port and .git; "" for a path."""
    u = url.strip()
    if "://" in u:
        scheme, _, rest = u.partition("://")
        if scheme.lower() == "file" or "/" not in rest:
            return ""
        host, _, path = rest.partition("/")
        host = host.rpartition("@")[2]
        if ":" in host and not host.endswith("]"):
            host = host[:host.rindex(":")]
    else:
        c = u.find(":")
        if c <= 0 or "/" in u[:c]:
            return ""
        host, path = u[:c].rpartition("@")[2], u[c + 1:]
    path = path.strip("/")
    path = path[:-4] if path.endswith(".git") else path
    path = path.strip("/")
    if not host or not path:
        return ""
    return (host + "/" + path).lower()


def parse_time(s: str) -> datetime:
    s = s.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*?\.\d{6})\d*(.*)$", s)
    if m:
        s = m.group(1) + m.group(2)
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def state_at(versions: list[dict], t: datetime) -> dict | None:
    """The highest version created at or before t, by its created time alone. A version that changes only metadata
    copies the created time of the one before, so this is not the version in force; see plausible_versions."""
    best = None
    for v in versions:
        if parse_time(v["created"]) <= t and (best is None or v["version"] > best["version"]):
            best = v
    return best


def dated(versions: list[dict]) -> list[bool]:
    """Which versions carry the time they were written. Add, Correct, Retire, Restore and SplitFact stamp the time of
    the write; Relabel, Retag and SetQueries change only metadata and copy the created time of the version before
    (internal/store/store.go). A version with the content and status of the one before is taken for the second kind."""
    out, prev = [], None
    for v in versions:
        out.append(prev is None or v.get("content") != prev.get("content") or v.get("status") != prev.get("status"))
        prev = v
    return out


def plausible_versions(versions: list[dict], t: datetime, snapshot: datetime | None = None,
                       stamps: list[bool] | None = None, times: list[datetime] | None = None) -> list[dict]:
    """Every version that may have been in force at t. The last dated version created by t had been written; each
    metadata-only version after it was written at some unknown time between the versions around it, so it may or may
    not have been. A snapshot taken by t settles them: every version of the copy had been written. Empty when the fact
    did not exist yet."""
    stamps = dated(versions) if stamps is None else stamps
    times = [parse_time(v["created"]) for v in versions] if times is None else times
    last = None
    for i in range(len(versions)):
        if stamps[i] and times[i] <= t:
            last = i
    if last is None:
        return []
    out = [versions[last]]
    floor = max(times[:last + 1])
    for j in range(last + 1, len(versions)):
        if stamps[j]:
            break
        floor = max(floor, times[j])
        if floor > t:
            break
        out.append(versions[j])
    if snapshot is not None and snapshot <= t:
        return out[-1:]
    return out


def day_end(day: str, tz_minutes: int) -> datetime:
    """The last instant of a calendar day in a fixed UTC offset."""
    d = datetime.strptime(day, "%Y-%m-%d")
    return d.replace(hour=23, minute=59, second=59, microsecond=999999,
                     tzinfo=timezone(timedelta(minutes=tz_minutes)))


def local_day(t: datetime, tz_minutes: int) -> str:
    return (t.astimezone(timezone.utc) + timedelta(minutes=tz_minutes)).strftime("%Y-%m-%d")


def eligible_on(v: dict | None, day: str | None) -> bool:
    if v is None or v.get("status") != "active" or v.get("scope", "").lower().startswith("shelf:"):
        return False
    exp = v.get("expires", "")
    return not (exp and day and exp < day)


def eligible(v: dict | None, t: datetime, tz_minutes: int = 0) -> bool:
    """What a hook could serve at t: active, not past its last day on the local calendar, off the shelves."""
    return eligible_on(v, local_day(t, tz_minutes))


def origin_key(origin: str) -> str:
    origin = (origin or "").strip()
    head, sep, last = origin.rpartition(" ")
    if not sep or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", last):
        return ""
    return head.strip()


def key_scope(key: str) -> str:
    if key.startswith("dir:"):
        return key
    return "repo:" + key.lower()


def project_of(v: dict) -> str:
    """dream_scope.go projectOf: the repo: or dir: scope, else the project the origin names; "" for none."""
    scope = v.get("scope", "")
    low = scope.lower()
    if low.startswith("repo:"):
        return low
    if low.startswith("dir:"):
        return "dir:" + scope[4:]
    if scope:
        return ""
    k = origin_key(v.get("origin", ""))
    return key_scope(k) if k and k != "_global" else ""


def placed(v: dict, keys: list[str], host: str) -> bool:
    """recall.Query.Filter with no -in: in a repository, its facts, this host's and the global ones; outside one,
    every fact off the shelves."""
    if not any(k and not k.startswith("dir:") for k in keys):
        return True
    scope, origin = v.get("scope", "").lower(), v.get("origin", "")
    if scope == "global" or origin.startswith("_global ") or (host and scope == "host:" + host.lower()):
        return True
    return any(scope == ("repo:" + k).lower() or origin.startswith(k + " ") for k in keys if k)


def placed_union(v: dict, session_keys: list[str] | None, file_keys: list[str], host: str) -> bool | None:
    """The session's default places, widened by the repositories of the files read: their facts, this host's and the
    global ones. It only adds: what the session's places show stays shown. None when neither is known."""
    if session_keys is None and not file_keys:
        return None
    if session_keys is not None and placed(v, session_keys, host):
        return True
    if not file_keys:
        return False
    scope, origin = v.get("scope", "").lower(), v.get("origin", "")
    if scope == "global" or origin.startswith("_global ") or (host and scope == "host:" + host.lower()):
        return True
    return any(scope == key_scope(k).lower() or origin.startswith(k + " ") for k in file_keys if k)


def normalize_read(path: str, cwd: str, home: str) -> str | None:
    if not path:
        return None
    if path == "~" or path.startswith("~/"):
        path = home + path[1:]
    elif not path.startswith("/"):
        if not cwd:
            return None
        path = os.path.join(cwd, path)
    return os.path.normpath(path)


def command_paths(cmd: str, cwd: str, home: str) -> list[str]:
    """The files a shell command names: absolute, ~/ and, against cwd, relative ones and bare file names."""
    out = []
    for kind, p in extract_paths(cmd):
        if kind in ("abs", "home", "rel", "base"):
            n = normalize_read(p, cwd, home)
            if n and n not in out:
                out.append(n)
    return out


class GitResolver:
    """locate(dir) -> (root, keys, status) the way tier.Keys names a project, read-only. status is repo, outside, or
    unknown when the directory no longer exists (a removed worktree)."""

    def __init__(self, claude_dir: str = ""):
        self.claude_dir = os.path.realpath(claude_dir) if claude_dir else ""
        self.cache: dict[str, tuple] = {}

    def locate(self, path: str):
        if path not in self.cache:
            self.cache[path] = self._locate(path)
        return self.cache[path]

    def _locate(self, path: str):
        if not os.path.isdir(path):
            return None, [], "unknown"
        d = path
        while True:
            g = os.path.join(d, ".git")
            if os.path.isdir(g):
                common = g
                break
            if os.path.isfile(g):
                try:
                    line = Path(g).read_text("utf-8").strip()
                except OSError:
                    return None, [], "unknown"
                gitdir = os.path.normpath(os.path.join(d, line.removeprefix("gitdir:").strip()))
                cd = os.path.join(gitdir, "commondir")
                common = os.path.normpath(os.path.join(gitdir, Path(cd).read_text("utf-8").strip())) \
                    if os.path.isfile(cd) else gitdir
                break
            parent = os.path.dirname(d)
            if parent == d:
                return None, outside(path), "outside"
            d = parent
        main = os.path.dirname(common) if os.path.basename(common) == ".git" else common
        if self.claude_dir and os.path.realpath(main) == self.claude_dir:
            return d, ["_global"], "repo"
        remotes = git_remotes(os.path.join(common, "config"))
        names = sorted(remotes)
        order = (["origin"] if "origin" in remotes else []) + names
        keys: list[str] = []
        for name in order:
            k = normalize_remote(remotes[name])
            if k and k not in keys:
                keys.append(k)
        if not keys:
            keys = [] if temporary(main) else ["dir:" + main]
        return d, keys, "repo"


def git_remotes(config: str) -> dict[str, str]:
    remotes: dict[str, str] = {}
    current = None
    try:
        lines = Path(config).read_text("utf-8", errors="replace").splitlines()
    except OSError:
        return remotes
    for line in lines:
        s = line.strip()
        m = re.match(r'^\[\s*remote\s+"([^"]+)"\s*\]', s)
        if m:
            current = m.group(1)
        elif s.startswith("["):
            current = None
        elif current:
            kv = re.match(r"^url\s*=\s*(.*)$", s)
            if kv and current not in remotes:
                remotes[current] = kv.group(1).strip().strip('"')
    return remotes


def temporary(d: str) -> bool:
    return any(d == r or d.startswith(r + "/") for r in TEMP_ROOTS)


def outside(d: str) -> list[str]:
    if temporary(d):
        return []
    p = d
    while True:
        gm = os.path.join(p, "go.mod")
        if os.path.isfile(gm):
            for line in Path(gm).read_text("utf-8", errors="replace").splitlines():
                rest = line.strip()
                if rest.startswith("module") and (rest == "module" or rest[6] in " \t"):
                    mod = rest[6:].strip().strip('"')
                    if mod:
                        return [mod.lower()]
        parent = os.path.dirname(p)
        if parent == p:
            return ["dir:" + d]
        p = parent


def load_facts(root: Path) -> tuple[dict[str, list[dict]], Counter]:
    """Every fact file under root: id -> versions in version order, a repeated line once. Like store.ParseFacts, a
    line that is not a fact version, lines of two facts in one file, two different lines with one version number and
    one fact in two files raise ValueError: the history is refused, not guessed at."""
    facts: dict[str, list[dict]] = {}
    stats: Counter = Counter()
    for path in sorted(root.rglob("*.jsonl")):
        if path.name.startswith(".tmp"):
            continue
        stats["files"] += 1
        seen, versions = set(), []
        for n, line in enumerate(path.read_text("utf-8").split("\n"), 1):
            line = line.strip()
            if not line or line in seen:
                continue
            seen.add(line)
            try:
                v = json.loads(line)
                ok = isinstance(v, dict) and bool(v.get("id")) and isinstance(v.get("version"), int) and \
                    v["version"] >= 1 and v.get("status") in ("active", "retired") and bool(parse_time(v["created"]))
            except (ValueError, KeyError, TypeError, AttributeError):
                ok = False
            if not ok:
                raise ValueError(f"{path}: line {n} is not a fact version")
            versions.append(v)
        if not versions:
            continue
        ids = {v["id"] for v in versions}
        if len(ids) > 1:
            raise ValueError(f"{path}: versions of {len(ids)} facts in one file")
        numbers = Counter(v["version"] for v in versions)
        if any(c > 1 for c in numbers.values()):
            raise ValueError(f"{path}: two different versions with one number")
        if versions[0]["id"] in facts:
            raise ValueError(f"{path}: fact {versions[0]['id']} is in two files")
        versions.sort(key=lambda v: v["version"])
        stats["versions"] += len(versions)
        facts[versions[0]["id"]] = versions
    return facts, stats


class Index:
    """Paths of every version of every fact, keyed for lookup from a read path."""

    def __init__(self, facts: dict[str, list[dict]], resolver=None, today: str | None = None, home: str = "",
                 tz_minutes: int = 0, snapshot: datetime | None = None):
        self.facts = facts
        self.today = today
        self.tz_minutes = tz_minutes
        self.snapshot = snapshot
        # "today" is the end of that calendar day; without one it is the latest version, with no expiry.
        self.cutoff = day_end(today, tz_minutes) if today else None
        self.stamps = {fid: dated(vs) for fid, vs in facts.items()}
        self.times = {fid: [parse_time(v["created"]) for v in vs] for fid, vs in facts.items()}
        self.at_cutoff: dict[str, list[dict]] = {}
        self.ext: dict[str, dict[int, set]] = {}
        self.exact: dict[str, set] = defaultdict(set)    # absolute path -> (fid, kind, token)
        self.home: dict[str, set] = defaultdict(set)     # "~/x" -> (fid, kind, token)
        self.rel: dict[str, set] = defaultdict(set)
        self.dirs: dict[str, set] = defaultdict(set)     # absolute or ~/ directory
        self.base: dict[str, set] = defaultdict(set)
        self.moved: dict[str, set] = defaultdict(set)    # repository-relative path of an absolute one
        for fid, versions in facts.items():
            per = self.ext[fid] = {}
            for v in versions:
                per[v["version"]] = set(extract_paths(v.get("content", "")))
                for kind, tok in per[v["version"]]:
                    entry = (fid, kind, tok)
                    if kind == "abs":
                        self.exact[os.path.normpath(tok)].add(entry)
                    elif kind == "home":
                        self.home[os.path.normpath(tok)].add(entry)
                    elif kind == "rel":
                        self.rel[tok].add(entry)
                    elif kind in ("absdir", "homedir"):
                        self.dirs[os.path.normpath(tok)].add(entry)
                    else:
                        self.base[tok].add(entry)
        if resolver is not None:
            for p, entries in list(self.exact.items()) + [(home + k[1:], e) for k, e in self.home.items() if home]:
                root, keys, status = resolver.locate(os.path.dirname(p))
                if status == "repo" and root and keys and p.startswith(root + "/"):
                    for e in entries:
                        self.moved[p[len(root) + 1:]].add(e + (root, frozenset(keys)))

    def contains(self, v: dict | None, kind: str, tok: str) -> bool:
        return v is not None and (kind, tok) in self.ext[v["id"]].get(v["version"], ())

    def plausible(self, fid: str, t: datetime) -> list[dict]:
        if t == self.cutoff:
            if fid not in self.at_cutoff:
                self.at_cutoff[fid] = plausible_versions(self.facts[fid], t, self.snapshot, self.stamps[fid],
                                                         self.times[fid])
            return self.at_cutoff[fid]
        return plausible_versions(self.facts[fid], t, self.snapshot, self.stamps[fid], self.times[fid])

    def match(self, path: str, t: datetime, resolver, home: str, tz_minutes: int | None = None) -> dict:
        """Strong matches whose every plausible version at t matches ("asof"), those only some plausible version
        matches ("ambiguous"), the same two at the --today cutoff ("today", "today_ambiguous"), and loose matches."""
        tz = self.tz_minutes if tz_minutes is None else tz_minutes
        root, keys, status = resolver.locate(os.path.dirname(path))
        key_scopes = {key_scope(k) for k in keys}
        cands: list[tuple] = []  # (fid, kind, tok, how or a function of the version)
        for e in self.exact.get(path, ()):
            cands.append(e + ("abs",))
        under_home = bool(home) and path.startswith(home.rstrip("/") + "/")
        if under_home:
            for e in self.home.get("~" + path[len(home.rstrip("/")):], ()):
                cands.append(e + ("home",))
        # A path without an extension is taken for a directory, but one a Read opens is a file: an exact match counts.
        for e in self.dirs.get(path, ()):
            cands.append(e + ("abs",))
        if under_home:
            for e in self.dirs.get("~" + path[len(home.rstrip("/")):], ()):
                cands.append(e + ("home",))
        if status == "repo" and root and path.startswith(root + "/"):
            for fid, kind, tok, froot, fkeys in self.moved.get(path[len(root) + 1:], ()):
                if froot != root and fkeys & set(keys):
                    cands.append((fid, kind, tok, "abs_worktree"))
        comps = path.strip("/").split("/")
        for i in range(1, len(comps) - 1):
            rel = "/".join(comps[i:])
            for fid, kind, tok in self.rel.get(rel, ()):
                cands.append((fid, kind, tok, self._rel_how(path, rel, root, key_scopes, status)))
        d = os.path.dirname(path)
        while d not in ("/", ""):
            for e in self.dirs.get(d, ()):
                cands.append(e + ("dir",))
            if under_home and (d + "/").startswith(home.rstrip("/") + "/"):
                for e in self.dirs.get("~" + d[len(home.rstrip("/")):], ()):
                    cands.append(e + ("dir",))
            d = os.path.dirname(d)
        for e in self.base.get(os.path.basename(path), ()):
            cands.append(e + ("base",))

        out = {"asof": {}, "ambiguous": {}, "today": {}, "today_ambiguous": {}, "loose": {}, "chars": {}}
        rank = {h: i for i, h in enumerate(STRONG)}

        def outcomes(versions, at, kind, tok, how):
            res = []
            for v in versions:
                ok = eligible(v, at, tz) if at is not None else eligible_on(v, None)
                res.append((how(v) if callable(how) else how) if ok and self.contains(v, kind, tok) else None)
            return res

        def put(bucket, fid, h):
            if fid not in out[bucket] or rank[h] < rank[out[bucket][fid]]:
                out[bucket][fid] = h

        for fid, kind, tok, how in cands:
            pv = self.plausible(fid, t)
            res = outcomes(pv, t, kind, tok, how)
            strong = [h for h in res if h in rank]
            if pv and len(strong) == len(res):
                put("asof", fid, min(strong, key=rank.get))
            elif strong:
                put("ambiguous", fid, min(strong, key=rank.get))
            elif any(res):
                out["loose"].setdefault(fid, next(h for h in res if h))
            if strong:
                out["chars"][fid] = len(pv[0].get("content", ""))
            if self.cutoff is None:
                tv, at = self.facts[fid][-1:], None
            else:
                tv, at = self.plausible(fid, self.cutoff), self.cutoff
            res = outcomes(tv, at, kind, tok, how)
            strong = [h for h in res if h in rank]
            if tv and len(strong) == len(res):
                put("today", fid, min(strong, key=rank.get))
            elif strong:
                put("today_ambiguous", fid, min(strong, key=rank.get))
        for fid in out["asof"]:
            out["ambiguous"].pop(fid, None)
        for fid in out["today"]:
            out["today_ambiguous"].pop(fid, None)
        for fid in list(out["loose"]):
            if fid in out["asof"] or fid in out["ambiguous"]:
                del out["loose"][fid]
        return out

    @staticmethod
    def _rel_how(path, rel, root, key_scopes, status):
        def how(v: dict) -> str:
            project = project_of(v)
            if project.startswith("dir:"):
                return "rel" if os.path.join(project[4:], rel) == path else "rel_other_project"
            if not project:
                return "rel_no_project"
            if status == "unknown":
                return "rel_unresolved"
            if status == "repo" and project in key_scopes and root + "/" + rel == path:
                return "rel"
            return "rel_other_project"
        return how


def read_claude(projects: Path, exclude: set[str], stand_markers: list[str]):
    """Read and Bash tool_use blocks of assistant records, each tool_use id once. Tool results, request copies and
    other record types are never read."""
    reads, bashes, seen = [], [], set()
    stats: Counter = Counter()
    sessions: dict[str, set] = defaultdict(set)
    for f in sorted(projects.rglob("*.jsonl")):
        stats["files"] += 1
        sub = "/subagents/" in str(f)
        for line in f.read_text("utf-8", errors="replace").split("\n"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                stats["bad_lines"] += 1
                continue
            if not isinstance(r, dict) or r.get("type") != "assistant":
                continue
            content = (r.get("message") or {}).get("content") or []
            for c in content if isinstance(content, list) else []:
                if not isinstance(c, dict) or c.get("type") != "tool_use" or c.get("name") not in ("Read", "Bash"):
                    continue
                if c.get("id") in seen:
                    stats["duplicate_calls"] += 1
                    continue
                seen.add(c.get("id"))
                sid, cwd = r.get("sessionId", ""), r.get("cwd", "")
                if sid in exclude:
                    cls = "own"
                elif any(mk in cwd for mk in stand_markers):
                    cls = "stand"
                elif sub or r.get("isSidechain"):
                    cls = "subagent"
                else:
                    cls = "main"
                inp = c.get("input") or {}
                rec = {"src": "claude", "id": c.get("id"), "session": sid, "t": r.get("timestamp", ""), "cwd": cwd,
                       "cls": cls}
                sessions[cls].add(sid)
                if c["name"] == "Read":
                    reads.append(dict(rec, path=inp.get("file_path", "")))
                else:
                    bashes.append(dict(rec, command=inp.get("command", "")))
    stats.update({f"sessions_{k}": len(v) for k, v in sessions.items()})
    return reads, bashes, dict(stats)


def read_hermes(db: Path):
    """read_file and terminal calls of state.db messages, each call id once, opened read-only."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        sessions = {sid: (src or "", cwd or "") for sid, src, cwd in
                    con.execute("select id, source, cwd from sessions")}
        rows = con.execute("select session_id, tool_calls, timestamp from messages "
                           "where tool_calls is not null and tool_calls != '' order by id").fetchall()
    finally:
        con.close()
    reads, terms, seen = [], [], set()
    stats: Counter = Counter()
    for sid, tc, ts in rows:
        try:
            calls = json.loads(tc)
        except ValueError:
            stats["bad_rows"] += 1
            continue
        for call in calls if isinstance(calls, list) else []:
            fn = (call.get("function") or {}) if isinstance(call, dict) else {}
            name = fn.get("name")
            if name not in ("read_file", "terminal"):
                continue
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    stats["bad_args"] += 1
                    continue
            key = call.get("id") or f"{sid}:{ts}:{json.dumps(args, sort_keys=True)}"
            if key in seen:
                stats["duplicate_calls"] += 1
                continue
            seen.add(key)
            src, cwd = sessions.get(sid, ("", ""))
            rec = {"src": "hermes", "id": key, "session": sid,
                   "t": datetime.fromtimestamp(ts, timezone.utc).isoformat(), "cwd": cwd, "cls": src}
            if name == "read_file":
                reads.append(dict(rec, path=args.get("path", "")))
            else:
                terms.append(dict(rec, command=args.get("command", ""), cwd=args.get("workdir") or cwd))
    stats["sessions"] = len(sessions)
    return reads, terms, dict(stats)


def fact_records(facts, today, home, tz_minutes=0, snapshot=None):
    """One line per fact as of the end of --today in the given UTC offset: a fact created later is "future", one
    whose plausible versions at that instant differ in status, scope, origin or expiry is marked uncertain and
    described by the latest of them."""
    cutoff = day_end(today, tz_minutes)
    out = []
    for fid, versions in facts.items():
        pv = plausible_versions(versions, cutoff, snapshot)
        if not pv:
            out.append({"id": fid, "versions": len(versions), "status": "future", "shelf": False,
                        "scope_class": "", "project": "", "paths": [], "exists_here": False, "macos_home": False,
                        "uncertain": False})
            continue
        last = pv[-1]
        uncertain = len({(v["status"], v.get("scope", ""), v.get("origin", ""), v.get("expires", "")) for v in pv}) > 1
        status = last["status"]
        if status == "active" and last.get("expires") and last["expires"] < today:
            status = "expired"
        paths = extract_paths(last.get("content", ""))
        files = [p for k, p in paths if k in ("abs", "home")]
        out.append({"id": fid, "versions": len(versions), "status": status, "uncertain": uncertain,
                    "shelf": last.get("scope", "").lower().startswith("shelf:"),
                    "scope_class": (last.get("scope", "").split(":")[0] or "(empty)"),
                    "project": project_of(last), "paths": paths,
                    "exists_here": any(os.path.exists(normalize_read(p, "", home) or "") for p in files),
                    "macos_home": any(p.startswith("/Users/") for p in files)})
    return out


def check_inputs(args) -> str:
    """Why a named input cannot be read, or "": a missing or wrong-typed input is an error, not an empty corpus."""
    named = [("--facts", args.facts, "dir"), ("--claude-projects", args.claude_projects, "dir"),
             ("--hermes-state", args.hermes_state, "file")]
    for flag, value, kind in named:
        if value is None:
            continue
        if kind == "dir" and not (os.path.isdir(value) and os.access(value, os.R_OK | os.X_OK)):
            return f"{flag} {value} is not a readable directory"
        if kind == "file" and not (os.path.isfile(value) and os.access(value, os.R_OK)):
            return f"{flag} {value} is not a readable file"
    return ""


def measure(args) -> int:
    problem = check_inputs(args)
    if problem:
        print(problem, file=sys.stderr)
        return 2
    try:
        facts, fstats = load_facts(Path(args.facts))
        snapshot = parse_time(args.snapshot_time) if args.snapshot_time else None
    except (ValueError, OSError) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    inputs = [p for p in (args.facts, args.claude_projects, args.hermes_state) if p is not None]
    out = safe_out(args.out, inputs)
    if out is None:
        return 2
    resolver = GitResolver(args.claude_dir or os.path.join(args.home, ".claude"))
    t0 = time.perf_counter()
    index = Index(facts, resolver=resolver, today=args.today, home=args.home, tz_minutes=args.tz_minutes,
                  snapshot=snapshot)
    build_s = time.perf_counter() - t0
    sources = {}
    if args.claude_projects is not None:
        reads, bashes, st = read_claude(Path(args.claude_projects), set(args.exclude_session or []),
                                        args.stand_marker or [])
        sources.update(claude_read=reads, claude_bash=bashes)
        fstats.update({"claude_" + k: v for k, v in st.items()})
    if args.hermes_state is not None:
        reads, terms, st = read_hermes(Path(args.hermes_state))
        sources.update(hermes_read=reads, hermes_terminal=terms)
        fstats.update({"hermes_" + k: v for k, v in st.items()})
    calls, timing = [], {}
    buckets = ("asof", "ambiguous", "today", "today_ambiguous", "loose", "chars")
    for name, recs in sources.items():
        t1 = time.perf_counter()
        n_paths = 0
        for rec in recs:
            paths = [normalize_read(rec["path"], rec["cwd"], args.home)] if "path" in rec else \
                command_paths(rec["command"], rec["cwd"], args.home)
            paths = [p for p in paths if p]
            n_paths += len(paths)
            row = {"source": name, "id": rec["id"], "session": rec["session"], "cls": rec["cls"], "t": rec["t"],
                   "resolved": bool(paths), "paths": paths, **{b: {} for b in buckets},
                   "placed_session": None, "placed_session_unsure": None, "placed_file": None,
                   "placed_file_unsure": None}
            if paths and rec["t"]:
                t = parse_time(rec["t"])
                _, skeys, sstatus = resolver.locate(rec["cwd"]) if rec["cwd"] else (None, [], "outside")
                session_keys = None if sstatus == "unknown" else skeys
                file_keys: list[str] = []
                for p in paths:
                    r = index.match(p, t, resolver, args.home, args.tz_minutes)
                    for b in buckets:
                        for k, v in r[b].items():
                            row[b].setdefault(k, v)
                    _, fk, fst = resolver.locate(os.path.dirname(p))
                    file_keys += fk if fst == "repo" else []
                for k in row["asof"]:
                    row["ambiguous"].pop(k, None)
                for k in row["today"]:
                    row["today_ambiguous"].pop(k, None)
                for k in list(row["loose"]):
                    if k in row["asof"] or k in row["ambiguous"]:
                        del row["loose"][k]
                # A place is certain when every plausible version of the fact at the call is in it.
                pv = {fid: index.plausible(fid, t) for fid in row["asof"]}
                if session_keys is not None:
                    seen = {f: [placed(v, session_keys, args.host) for v in vs] for f, vs in pv.items()}
                    row["placed_session"] = sorted(f for f, ok in seen.items() if all(ok))
                    row["placed_session_unsure"] = sorted(f for f, ok in seen.items() if any(ok) and not all(ok))
                if session_keys is not None or file_keys:
                    seen = {f: [placed_union(v, session_keys, file_keys, args.host) for v in vs]
                            for f, vs in pv.items()}
                    row["placed_file"] = sorted(f for f, ok in seen.items() if all(ok))
                    row["placed_file_unsure"] = sorted(f for f, ok in seen.items() if any(ok) and not all(ok))
            calls.append(row)
        dt = time.perf_counter() - t1
        timing[name] = {"calls": len(recs), "paths": n_paths, "seconds": round(dt, 4),
                        "us_per_path": round(dt / n_paths * 1e6, 1) if n_paths else None}
    frecs = fact_records(facts, args.today, args.home, args.tz_minutes, snapshot)
    # meta and summary hold counts, dates and timings only: no host, path, session or fact ID.
    meta = {"today": args.today, "tz_minutes": args.tz_minutes, "snapshot_time": args.snapshot_time,
            "inputs": fstats, "index_build_seconds": round(build_s, 4), "match_timing": timing,
            "sources": sorted(sources)}
    write_jsonl(out / "facts.jsonl", frecs)
    write_jsonl(out / "calls.jsonl", calls)
    write_json(out / "meta.json", meta)
    write_json(out / "summary.json", summarize_rows(frecs, calls, meta))
    print(f"wrote {out}", file=sys.stderr)
    return 0


def block(rows: list[dict]) -> dict:
    hows = {"asof": "asof", "placed_session": "asof", "placed_file": "asof", "ambiguous": "ambiguous"}

    def facts_of(r: dict, key: str) -> list:
        value = r.get(key)
        return list(value) if isinstance(value, dict) else (value or [])

    def part(key: str) -> dict:
        hit = [r for r in rows if facts_of(r, key)]
        seen_fact: set = set()
        per_session: dict = defaultdict(dict)
        chars_sum = 0
        by_how: Counter = Counter()
        for r in hit:
            fs = facts_of(r, key)
            seen_fact.update(fs)
            if key in hows:
                for f in fs:
                    chars_sum += r["chars"].get(f, 0)
                    per_session[r["session"]].setdefault(f, r["chars"].get(f, 0))
                for h in {r[hows[key]][f] for f in fs}:
                    by_how[h] += 1
        res = {"calls": len(hit), "sessions": len({r["session"] for r in hit}), "unique_facts": len(seen_fact)}
        if key in hows:
            res.update(chars_per_call_sum=chars_sum,
                       chars_per_session_unique=sum(sum(v.values()) for v in per_session.values()),
                       by_how=dict(sorted(by_how.items())))
        return res

    loose = Counter()
    for r in rows:
        for h in set(r["loose"].values()):
            loose[h] += 1
    times = sorted(r["t"] for r in rows if r["t"])
    known = [r for r in rows if r["placed_session"] is not None]
    return {"calls": len(rows), "sessions": len({r["session"] for r in rows}),
            "unresolved_path": sum(not r["resolved"] for r in rows),
            "first": times[0] if times else None, "last": times[-1] if times else None,
            "asof": part("asof"), "asof_ambiguous_only": part("ambiguous"),
            "today": part("today"), "today_ambiguous_only": part("today_ambiguous"),
            "asof_placed_session": dict(part("placed_session"), calls_session_known=len(known)),
            "asof_placed_session_unsure": part("placed_session_unsure"),
            "asof_placed_file": part("placed_file"), "asof_placed_file_unsure": part("placed_file_unsure"),
            "loose_calls_by_how": dict(sorted(loose.items())),
            "loose_calls_any": sum(bool(r["loose"]) for r in rows)}


def summarize_rows(frecs: list[dict], calls: list[dict], meta: dict) -> dict:
    active = [f for f in frecs if f["status"] == "active"]
    served = [f for f in active if not f["shelf"]]
    kinds = ("abs", "home", "rel", "absdir", "homedir", "base")
    with_kind = {k: sum(any(pk == k for pk, _ in f["paths"]) for f in served) for k in kinds}
    has = lambda f, ks: any(pk in ks for pk, _ in f["paths"])  # noqa: E731
    rel_facts = [f for f in served if has(f, ("rel",))]
    facts = {"files": meta["inputs"].get("files"), "versions": meta["inputs"].get("versions"),
             "status_at_cutoff": dict(sorted(Counter(f["status"] for f in frecs).items())),
             "uncertain_at_cutoff": sum(f.get("uncertain", False) for f in frecs), "active": len(active),
             "active_on_shelf": len(active) - len(served), "with_kind": with_kind,
             "with_file_path": sum(has(f, ("abs", "home", "rel")) for f in served),
             "with_exact_path": sum(has(f, ("abs", "home")) for f in served),
             "with_directory_only": sum(has(f, ("absdir", "homedir")) and not has(f, ("abs", "home", "rel"))
                                        for f in served),
             "basename_only": sum(has(f, ("base",)) and not has(f, ("abs", "home", "rel", "absdir", "homedir"))
                                  for f in served),
             "rel_with_project": sum(bool(f["project"]) for f in rel_facts),
             "rel_without_project": sum(not f["project"] for f in rel_facts),
             "exact_path_exists_here": sum(f["exists_here"] for f in served),
             "exact_path_macos_home": sum(f["macos_home"] for f in served),
             "with_file_path_by_scope": dict(sorted(Counter(f["scope_class"] for f in served
                                                            if has(f, ("abs", "home", "rel"))).items())),
             "active_on_shelf_with_file_path": sum(has(f, ("abs", "home", "rel")) for f in active if f["shelf"])}
    out = {"facts": facts, "meta": meta}
    for source in meta["sources"]:
        rows = [r for r in calls if r["source"] == source]
        by = {"all": block(rows)}
        for cls in sorted({r["cls"] for r in rows}):
            by[cls] = block([r for r in rows if r["cls"] == cls])
        if source.startswith("claude"):
            by["work"] = block([r for r in rows if r["cls"] in ("main", "subagent")])
        out[source] = by
    return out


def summarize(args) -> int:
    src = Path(args.inp)
    # Every input is read before the output directory is made: a missing or broken one leaves nothing behind.
    try:
        frecs = [json.loads(x) for x in (src / "facts.jsonl").read_text("utf-8").split("\n") if x]
        calls = [json.loads(x) for x in (src / "calls.jsonl").read_text("utf-8").split("\n") if x]
        meta = json.loads((src / "meta.json").read_text("utf-8"))
    except (OSError, ValueError) as e:
        print(f"--in {args.inp}: {e}", file=sys.stderr)
        return 2
    out = safe_out(args.out, [str(src)])
    if out is None:
        return 2
    write_json(out / "summary.json", summarize_rows(frecs, calls, meta))
    print(f"wrote {out / 'summary.json'}", file=sys.stderr)
    return 0


def safe_out(out: str, inputs: list[str]) -> Path | None:
    """A new or empty directory that is neither inside an input nor holding one."""
    o = os.path.realpath(out)
    for i in inputs:
        r = os.path.realpath(i)
        if o == r or o.startswith(r.rstrip("/") + "/") or r.startswith(o.rstrip("/") + "/"):
            print(f"--out {out} overlaps the input {i}", file=sys.stderr)
            return None
    if os.path.lexists(o) and (not os.path.isdir(o) or os.listdir(o)):
        print(f"--out {out} exists and is not an empty directory", file=sys.stderr)
        return None
    os.makedirs(o, mode=0o700, exist_ok=True)
    os.chmod(o, 0o700)  # the mode makedirs gets is cut by the umask; an empty directory given may be open
    return Path(o)


def private_file(path: Path):
    """A new file only its owner can read, whatever the umask; an existing one is never overwritten."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.fchmod(fd, 0o600)
    return os.fdopen(fd, "w", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with private_file(path) as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, doc: dict) -> None:
    with private_file(path) as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure")
    m.add_argument("--facts", required=True)
    m.add_argument("--claude-projects")
    m.add_argument("--hermes-state")
    m.add_argument("--home", required=True)
    m.add_argument("--host", required=True)
    m.add_argument("--today", required=True)
    m.add_argument("--tz-minutes", type=int, default=0)
    m.add_argument("--snapshot-time", default="")
    m.add_argument("--claude-dir", default="")
    m.add_argument("--exclude-session", action="append")
    m.add_argument("--stand-marker", action="append")
    m.add_argument("--out", required=True)
    s = sub.add_parser("summarize")
    s.add_argument("--in", dest="inp", required=True)
    s.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    return measure(args) if args.cmd == "measure" else summarize(args)


if __name__ == "__main__":
    sys.exit(main())
