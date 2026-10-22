"""Build the "run it on your computer" bundle for the Codex extraction route.

    python tools/build_bundle.py --ref <tag> [--out DIR]

Run from the eps directory with the project's virtual environment. Writes
`eps-bundle.zip`, a copy of its README and a file list to DIR (default:
a staging folder beside the repository). Nothing is uploaded anywhere.

Code comes from the git ref, not the working tree. The harvested text files
are the one exception: a document's ID hashes its bytes as they sit in the
working tree (CRLF; DECISIONS H-104), so they are copied from there, after
checking that git sees no difference between them and the ref.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import ntpath
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

EPS = Path(__file__).resolve().parent.parent           # .../eps-pipeline/eps
EPS_REL = "scanner-code/eps-pipeline/eps"                 # EPS, relative to the repo
DEFAULT_OUT = EPS.parents[2].parent / "eps-bundle-staging"

#: Exactly the modules extract and build import (checked by importing
#: eps.extract, eps.harvest.local, eps.pipeline, eps.providers, eps.validate,
#: eps.context and eps.intention and listing sys.modules).
PACKAGE_FILES = [
    "src/eps/__init__.py", "src/eps/assemble.py", "src/eps/cli_schemas.py",
    "src/eps/context.py", "src/eps/intention.py",
    "src/eps/extract.py", "src/eps/jel.py", "src/eps/models.py",
    "src/eps/normalise.py", "src/eps/pipeline.py", "src/eps/providers.py",
    "src/eps/validate.py",
    "src/eps/harvest/__init__.py", "src/eps/harvest/local.py",
    "src/eps/harvest/store.py",
    "src/eps/sources/__init__.py", "src/eps/sources/blocks.py",
    "src/eps/sources/text.py",
    "src/eps/reference/officeholders.csv", "src/eps/reference/jel_codes.csv",
    "src/eps/reference/institutions.csv",
    "data/reference/jel_codes_active_20260828.csv",
    "data/reference/jel_classification_protocol_v2.0.txt",
    "data/reference/jel_taxonomy_compact.txt",
    "pyproject.toml",
]
#: Bundle files that sit at the bundle's root.
ROOT_FILES = [("bundle/run_pipeline.py", "run_pipeline.py"),
              ("bundle/README.md", "README.md"),
              ("bundle/INSTRUCTIONS_FOR_CODEX.md", "INSTRUCTIONS_FOR_CODEX.md"),
              # Codex reads AGENTS.md by itself when this folder is its project.
              ("bundle/INSTRUCTIONS_FOR_CODEX.md", "AGENTS.md"),
              ("bundle/requirements.txt", "requirements.txt")]

#: The harvests, in the order the runner works through them. The July lists
#: are subsets of the full ones, so they come first and the full lists then
#: skip what is already done. Only the full lists are built: the July
#: datasets are their July rows, and building them separately would pay for
#: the same context and intention calls twice.
HARVESTS = [
    {"name": "jul2026-uk", "folder": "uk", "file": "snapshot_jul2026.csv",
     "source": f"{EPS_REL}/manifest_jul2026_uk.csv"},
    {"name": "jul2026-us", "folder": "us", "file": "snapshot_jul2026.csv",
     "source": f"{EPS_REL}/manifest_jul2026_us.csv"},
    {"name": "uk-full", "folder": "uk", "file": "manifest.csv", "build": True,
     "source": "harvest-code/uk-harvest/manifest_uk_full.csv"},
    {"name": "us-full", "folder": "us", "file": "manifest.csv", "build": True,
     "source": "harvest-code/us-harvest/manifest_us_full.csv"},
]
DOCUMENT_DIRS = {"uk": "harvest-code/uk-harvest/documents_v2",
                 "us": "harvest-code/us-harvest/documents"}
SIDECAR = ".blocks.json"

CREDENTIAL_PATTERNS = [
    re.compile(p) for p in (
        r"sk-ant-[A-Za-z0-9_\-]{8,}", r"sk-proj-[A-Za-z0-9_\-]{8,}",
        r"\bsk-[A-Za-z0-9]{32,}", r"\bAKIA[0-9A-Z]{16}\b", r"\bghp_[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}", r"\bxox[abposr]-[A-Za-z0-9\-]{10,}",
        r"\bAIza[0-9A-Za-z_\-]{30,}", r"[A-Z0-9_]*API_KEY\s*=\s*['\"]?[^\s'\"]{6,}",
        r"Bearer\s+[A-Za-z0-9\-_.=]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"(?i)\b(?:access|refresh|auth)_token['\"]?\s*[:=]\s*['\"][^'\"]{12,}",
    )
]
FORBIDDEN_PARTS = {".git", ".venv", "__pycache__", "harvest-code"}


def git(*args: str, binary: bool = False):
    out = subprocess.run(["git", *args], cwd=EPS, capture_output=True, check=True)
    return out.stdout if binary else out.stdout.decode("utf-8").strip()


def show(ref: str, path: str) -> bytes:
    return git("show", f"{ref}:{path}", binary=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(ref: str, out_dir: Path) -> int:
    repo = Path(git("rev-parse", "--show-toplevel"))
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}")
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", ref)
    out_dir.mkdir(parents=True, exist_ok=True)
    # The unpacked copy and the file list always stay in the local staging
    # folder: only the zip and its README go to --out (Google Drive).
    DEFAULT_OUT.mkdir(parents=True, exist_ok=True)
    stage = DEFAULT_OUT / "eps-bundle"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    print(f"ref {ref} = {commit[:10]}  ->  {out_dir}")

    # The data must be what the ref says it is (modulo line endings).
    data_paths = list(DOCUMENT_DIRS.values()) + [h["source"] for h in HARVESTS]
    diff = subprocess.run(["git", "diff", "--quiet", commit, "--", *data_paths],
                          cwd=repo)
    if diff.returncode != 0:
        raise SystemExit("the harvest files in the working tree differ from "
                         f"{ref}; commit or restore them first")

    # 1. code, from the ref
    for rel in PACKAGE_FILES:
        dest = stage / "eps" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(show(commit, f"{EPS_REL}/{rel}"))
    for rel, name in ROOT_FILES:
        (stage / name).write_bytes(show(commit, f"{EPS_REL}/{rel}"))

    # 2. harvests: manifests rewritten to paths relative to themselves, and
    #    only the documents (and sidecars) a manifest names
    tracked = {f: set(git("ls-tree", "-r", "--name-only", "--full-tree", commit,
                          "--", d).splitlines())
               for f, d in DOCUMENT_DIRS.items()}
    shipped: dict[str, set[str]] = {"uk": set(), "us": set()}
    listing = []
    for h in HARVESTS:
        text = show(commit, h["source"]).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(text)))
        fields = list(rows[0].keys())
        folder = h["folder"]
        src_dir = repo / DOCUMENT_DIRS[folder]
        dest_dir = stage / "harvests" / folder / "documents"
        dest_dir.mkdir(parents=True, exist_ok=True)
        for row in rows:
            name = ntpath.basename(row["path"].replace("/", "\\"))
            src = src_dir / name
            if f"{DOCUMENT_DIRS[folder]}/{name}" not in tracked[folder]:
                raise SystemExit(f"{h['name']}: {name} is not tracked at {ref}")
            if name not in shipped[folder]:
                shutil.copyfile(src, dest_dir / name)
                side = src.with_name(src.stem + SIDECAR)
                if side.exists():
                    shutil.copyfile(side, dest_dir / side.name)
                shipped[folder].add(name)
            row["path"] = f"documents/{name}"
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
        (stage / "harvests" / folder / h["file"]).write_text(buf.getvalue(),
                                                             encoding="utf-8")
        listing.append({"name": h["name"], "manifest": f"{folder}/{h['file']}",
                        "build": h.get("build", False)})
        print(f"  {h['name']:<11} {len(rows):>5} documents")

    # The July lists must be subsets of the full ones: nothing duplicated.
    for folder in ("uk", "us"):
        full = {r["path"] for r in csv.DictReader(open(
            stage / "harvests" / folder / "manifest.csv", encoding="utf-8", newline=""))}
        snap = {r["path"] for r in csv.DictReader(open(
            stage / "harvests" / folder / "snapshot_jul2026.csv", encoding="utf-8", newline=""))}
        if not snap <= full:
            raise SystemExit(f"{folder}: the July list is not a subset of the full one")
    (stage / "harvests" / "harvests.json").write_text(
        json.dumps(listing, indent=2), encoding="utf-8")
    (stage / "BUNDLE_VERSION.txt").write_text(
        f"ref {ref}\ncommit {commit}\n", encoding="utf-8")

    # 3. what ingest produces from these files, with the ref's own code
    subprocess.run([sys.executable, "-I", "-B", str(stage / "run_pipeline.py"),
                    "--write-reference", str(stage / "reference_units.json")],
                   cwd=stage, check=True)

    # 4. exclusions, then checksums over every file
    files = sorted(p for p in stage.rglob("*") if p.is_file())
    for p in files:
        parts = set(p.relative_to(stage).parts)
        if parts & FORBIDDEN_PARTS or p.name == ".env" or p.suffix == ".env" \
                or p.name.endswith((".bak", ".pyc")):
            raise SystemExit(f"excluded file reached the bundle: {p}")
    sums = [f"{sha256(p.read_bytes())}  {p.relative_to(stage).as_posix()}"
            for p in files]
    (stage / "CHECKSUMS.sha256").write_text("\n".join(sums) + "\n", encoding="utf-8")
    files = sorted(p for p in stage.rglob("*") if p.is_file())

    # 5. credential scan
    hits = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for pat in CREDENTIAL_PATTERNS:
            for m in pat.finditer(text):
                hits.append(f"{p.relative_to(stage).as_posix()}: {m.group(0)[:40]}")
    print(f"credential scan: {len(hits)} hit(s)")
    for h in hits:
        print(f"  ! {h}")

    # 6. zip (one top-level folder), README alongside, file list
    zip_path = out_dir / "eps-bundle.zip"   # fixed: the README's commands name it
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in files:
            z.write(p, f"eps-bundle/{p.relative_to(stage).as_posix()}")
    shutil.copyfile(stage / "README.md", out_dir / "README.md")
    total = sum(p.stat().st_size for p in files)
    list_path = DEFAULT_OUT / f"eps-bundle-{label}.files.txt"
    list_path.write_text(
        "".join(f"{p.stat().st_size:>10}  {p.relative_to(stage).as_posix()}\n"
                for p in files)
        + f"\n{len(files)} files, {total:,} bytes unpacked\n", encoding="utf-8")

    areas: dict[str, list[int]] = {}
    for p in files:
        rel = p.relative_to(stage).parts
        key = "/".join(rel[:3]) if rel[0] == "harvests" and len(rel) > 3 else \
              rel[0] if len(rel) > 1 else "(root)"
        areas.setdefault(key, [0, 0])
        areas[key][0] += 1
        areas[key][1] += p.stat().st_size
    for key, (n, size) in sorted(areas.items()):
        print(f"  {key:<28} {n:>6} files {size / 1e6:>8.1f} MB")
    print(f"{len(files)} files, {total / 1e6:.1f} MB unpacked; "
          f"zip {zip_path.stat().st_size / 1e6:.1f} MB -> {zip_path}")
    print(f"file list -> {list_path}")
    return 1 if hits else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ref", required=True, help="git tag (or commit) to build from")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help=f"where to write the zip (default {DEFAULT_OUT})")
    args = p.parse_args(argv)
    return build(args.ref, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
