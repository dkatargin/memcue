"""Build the inputs of the #601 stand: python3 -I make_inputs.py REPO MEMCUE_BINARY OUT.

OUT is a new directory. It gets the memcue binary, the shipped Claude Code plugin of REPO as plugin-base, the same
plugin with the candidate line as plugin-cand, the container scripts and manifest.json with the sha256 of every file.
The candidate differs in one place: the SessionStart part-1 hook pipes its output through reminder601.py, which adds
the line of candidate/reminder.md at the end of the memory note. The build stops if the part-1 command is not found
exactly once or if anything else in the two plugins differs.
"""

import filecmp
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PART1 = 'sh "${CLAUDE_PLUGIN_ROOT}/scripts/memcue.sh" session-start -part 1 || true'
PART1_CAND = ('sh "${CLAUDE_PLUGIN_ROOT}/scripts/memcue.sh" session-start -part 1 | '
              'python3 -I "${CLAUDE_PLUGIN_ROOT}/scripts/reminder601.py" || true')


def main() -> int:
    repo, binary, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    out.mkdir(parents=True)  # a new directory: an existing one is an error
    src = repo / "plugins" / "claude-code"
    for arm in ("base", "cand"):
        shutil.copytree(src, out / f"plugin-{arm}", ignore=shutil.ignore_patterns("test", "node_modules"))
    cand = out / "plugin-cand"
    hooks_path = cand / "hooks" / "hooks.json"
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    found = [h for g in hooks["hooks"]["SessionStart"] for h in g["hooks"] if h["command"] == PART1]
    if len(found) != 1:
        sys.exit(f"the part-1 command occurs {len(found)} times, not once")
    found[0]["command"] = PART1_CAND
    hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(HERE / "reminder601.py", cand / "scripts" / "reminder601.py")
    shutil.copy2(HERE.parent / "candidate" / "reminder.md", cand / "scripts" / "reminder.md")
    cmp = filecmp.dircmp(out / "plugin-base", cand)
    differ = sorted(cmp.diff_files) + sorted(cmp.left_only) + sorted(cmp.right_only)
    for sub in cmp.subdirs.values():
        differ += [f"{sub.left}/{x}" for x in sub.diff_files + sub.left_only + sub.right_only]
    expected = {"hooks.json", "reminder601.py", "reminder.md"}
    if {Path(x).name for x in differ} != expected:
        sys.exit(f"the plugins differ in {differ}, not only in {sorted(expected)}")
    shutil.copy2(binary, out / "memcue")
    (out / "memcue").chmod(0o755)
    for name in ("agent601.sh", "grade601.sh"):
        shutil.copy2(HERE / name, out / name)
    print(json.dumps({"inputs": str(out), "differ": differ}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
