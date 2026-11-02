"""Offline check of the #601 archive. It reads files only: no docker, no subprocess, no model.

    python3 -I archive601.py --root ROOT --frozen results/FROZEN.json [--expect results/ARCHIVE_MANIFEST.json]
                             [--json OUT]

ROOT is a copy of the stand root: inputs/ (with manifest.json), fixtures/ and runs/<phase>/<arm>/<scenario>/r<n>/.
Every hash it relies on is computed again from the files: the per-file sha256 of the inputs, their aggregate digest
(sha256 of the sorted file list, as the stand's manifest defines it), the fixtures. It then checks that the
manifest's own file list and digest agree with the files, that the digest and the frozen files match FROZEN.json,
that the fixtures match FROZEN.json, that every attempt has no symlink or special file in what is read, a saved
docker_exit of 0, the recomputed inputs digest and one image id, the model and Claude Code version its streams
report, and that every probe started from its capture's final base. With --expect the whole result must equal the
published one. Exit 1 on any problem.

The image id is the one each run.json recorded; nothing here inspects the image itself. The runs saved no plan
before they started, so the result is a reconstruction from the archive, not a saved plan.
"""

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("records601", HERE / "records601.py")
records601 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records601)

STREAMS = {"capture": ("turn1.jsonl", "turn2.jsonl"), "probe": ("probe.jsonl",), "reference": ("probe.jsonl",)}
PLAN = "none saved before the runs; manifest reconstructed from the archive after the run"
IMAGE_CHECK = "image ids as each run.json recorded them; the image itself was not inspected offline"


class ArchiveError(Exception):
    pass


def file_hashes(top: Path) -> dict[str, str]:
    """sha256 of every regular file under top except manifest.json; a symlink is an error."""
    out = {}
    for p in sorted(top.rglob("*")):
        if p.is_symlink():
            raise ArchiveError(f"{p.relative_to(top)} is a symlink")
        if p.is_file() and p.name != "manifest.json":
            out[str(p.relative_to(top))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def digest(files: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def _differ(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def verify(root: Path, frozen: dict, expect: dict | None = None) -> dict:
    problems: list[str] = []
    inputs = root / "inputs"
    try:
        files = file_hashes(inputs)
    except (OSError, ArchiveError) as e:
        files = {}
        problems.append(f"inputs: {e}")
    recomputed = digest(files)
    try:
        man = json.loads(records601.read_nofollow(inputs / "manifest.json"))
    except (OSError, ValueError) as e:
        man = {}
        problems.append(f"inputs/manifest.json: {e}")
    if man.get("files") != files:
        problems.append(f"inputs/manifest.json lists other hashes than the files have: "
                        f"{_differ(man.get('files') or {}, files)}")
    if man.get("sha256") != recomputed:
        problems.append(f"inputs/manifest.json digest {man.get('sha256')} is not the digest of the files "
                        f"{recomputed}")
    if recomputed != frozen.get("inputs_manifest_sha256"):
        problems.append(f"inputs digest {recomputed} is not the frozen {frozen.get('inputs_manifest_sha256')}")
    for k, v in sorted((frozen.get("inputs") or {}).items()):
        if files.get(k) != v:
            problems.append(f"inputs/{k}: sha256 {files.get(k)} is not the frozen {v}")
    try:
        fx = {f"fixtures/{k}": v for k, v in file_hashes(root / "fixtures").items()}
    except (OSError, ArchiveError) as e:
        fx = {}
        problems.append(f"fixtures: {e}")
    want = {k: v for k, v in (frozen.get("fixtures") or {}).items() if k.startswith("fixtures/")}
    for k in _differ(fx, want):
        problems.append(f"{k}: sha256 {fx.get(k)} is not the frozen {want.get(k)}")

    images, hashes, models, versions = set(), set(), set(), set()
    attempts, probes = 0, 0
    for d in sorted((root / "runs").glob("*/*/*/*")):
        if d.name.startswith("."):
            continue
        attempts += 1
        rel = str(d.relative_to(root))
        phase = d.parts[-4]
        try:
            records601.check_outputs(d)
            meta = json.loads(records601.read_nofollow(d / "run.json"))
        except (OSError, ValueError, records601.ExtractError) as e:
            problems.append(f"{rel}: {type(e).__name__}: {e}")
            continue
        if type(meta.get("docker_exit")) is not int or meta["docker_exit"] != 0:
            problems.append(f"{rel}: docker_exit {meta.get('docker_exit', 'missing')!r}, not 0")
        images.add(meta.get("image"))
        hashes.add(meta.get("inputs_sha256"))
        for name in STREAMS.get(phase, ()):
            try:
                init = records601.parse_stream(d / "rec" / name)["init"]
                models.add(init.get("model"))
                versions.add(init.get("claude_code_version"))
            except records601.ExtractError as e:
                problems.append(f"{rel}: {e}")
        if phase == "probe" and d.name[1:].isdigit():
            probes += 1
            cap = root / str(meta.get("capture_run", "-"))
            try:
                same = records601.snapshot(d / "rec" / "base-before" / "facts") == records601.snapshot(
                    cap / "rec" / "base-after2" / "facts")
            except (OSError, ValueError, records601.ExtractError):
                same = False
            if not same:
                problems.append(f"{rel}: its starting base is not the final base of {meta.get('capture_run')}")
    if len(images) != 1:
        problems.append(f"{len(images)} image ids across the attempts: {sorted(map(str, images))}")
    if hashes != {recomputed}:
        problems.append(f"inputs digests named by the attempts {sorted(map(str, hashes))} are not the recomputed "
                        f"{recomputed}")
    result = {"plan": PLAN, "image_check": IMAGE_CHECK, "inputs_sha256": recomputed, "inputs": files,
              "fixtures": fx, "images": sorted(map(str, images)), "models": sorted(map(str, models)),
              "claude_code_versions": sorted(map(str, versions)), "attempts": attempts,
              "probe_copies_checked": probes}
    if expect is not None:
        keys = _differ({k: v for k, v in expect.items() if k != "problems"}, result)
        if keys:
            problems.append(f"the result differs from ARCHIVE_MANIFEST in {keys}")
    result["problems"] = problems
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--frozen", type=Path, required=True)
    ap.add_argument("--expect", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    expect = json.loads(a.expect.read_text(encoding="utf-8")) if a.expect else None
    r = verify(a.root.resolve(), json.loads(a.frozen.read_text(encoding="utf-8")), expect)
    if a.json:
        a.json.write_text(json.dumps(r, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: r[k] for k in ("plan", "image_check", "inputs_sha256", "images", "models",
                                        "claude_code_versions", "attempts", "probe_copies_checked", "problems")},
                     indent=1))
    return 1 if r["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
