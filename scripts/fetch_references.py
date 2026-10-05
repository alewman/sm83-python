#!/usr/bin/env python3
"""Fetch the pinned documents, test ROMs, tools and source trees into reference/.

Nothing fetched here is committed (see .gitignore). Two pin files drive it:

- ``scripts/pinned_files.json``: one entry per file, with its URL, SHA-256 and
  kind. Kinds ``document``, ``test-rom`` and ``tool`` must match their hash
  exactly; a mismatch is an error and the file is not kept. Kind
  ``live-document`` is a URL that always serves the newest build (the GBCTR
  PDF); a mismatch there is a warning and the new bytes are kept, because the
  docs cite the build date recorded in the entry's note. A ``.zip`` test-rom is
  unpacked next to itself.
- ``scripts/pinned_repos.json``: one entry per git repository, cloned shallow at
  the pinned revision (sparse where the entry lists paths).

    python scripts/fetch_references.py            # everything missing
    python scripts/fetch_references.py --verify   # hash what is present, fetch nothing
    python scripts/fetch_references.py --no-tools # skip the 750 MB simulator bundle

Building the referees from what this fetches is scripts/build_referees.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "scripts" / "pinned_files.json"
REPOS = ROOT / "scripts" / "pinned_repos.json"
LIVE = {"live-document"}
USER_AGENT = "Mozilla/5.0 (sm83-python reference fetch)"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    # curl rather than urllib, as famicom-python does: it follows GitHub's
    # release redirects and streams the large tool bundle to disk.
    result = subprocess.run(
        ["curl", "-sSfL", "--max-time", "1800", "-A", USER_AGENT, "-o", str(target), url],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise OSError(result.stderr.decode("utf-8", "replace").strip())


def fetch_files(verify_only: bool, tools: bool) -> int:
    problems = 0
    for entry in json.loads(FILES.read_text(encoding="utf-8")):
        if entry["kind"] == "tool" and not tools:
            continue
        path = ROOT / entry["path"]
        live = entry["kind"] in LIVE
        if path.exists():
            if sha256(path) != entry["sha256"]:
                level = "warning" if live else "ERROR"
                print(f"{level}: {entry['path']} does not match its pin")
                problems += not live
            continue
        if verify_only:
            print(f"missing: {entry['path']}")
            problems += 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            partial = Path(handle.name)
        try:
            download(entry["url"], partial)
        except OSError as error:
            partial.unlink(missing_ok=True)
            print(f"ERROR: {entry['url']}: {error}")
            problems += 1
            continue
        digest = sha256(partial)
        if digest != entry["sha256"] and not live:
            partial.unlink()
            print(f"ERROR: {entry['url']} has SHA-256 {digest}, pinned {entry['sha256']}; not kept")
            problems += 1
            continue
        if digest != entry["sha256"]:
            print(f"warning: {entry['path']} changed since the pinned build")
        partial.replace(path)
        if entry["kind"] == "test-rom" and path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                archive.extractall(path.parent)
        print(f"fetched {entry['path']}")
    return problems


def fetch_repos(verify_only: bool) -> int:
    problems = 0
    for entry in json.loads(REPOS.read_text(encoding="utf-8")):
        path = ROOT / entry["path"]
        if path.exists():
            head = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            if head != entry["rev"]:
                print(f"ERROR: {entry['path']} is at {head}, pinned {entry['rev']}")
                problems += 1
            continue
        if verify_only:
            print(f"missing: {entry['path']}")
            problems += 1
            continue
        path.mkdir(parents=True)
        git = ["git", "-C", str(path)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "remote", "add", "origin", entry["url"]], check=True)
        if entry["sparse"]:
            # The pins are gitignore-style patterns (/dir/, /file), not cone directories.
            subprocess.run(
                [*git, "sparse-checkout", "set", "--no-cone", *entry["sparse"]], check=True
            )
        subprocess.run(
            [*git, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", entry["rev"]],
            check=True,
        )
        subprocess.run([*git, "checkout", "-q", "FETCH_HEAD"], check=True)
        print(f"cloned {entry['path']} at {entry['rev'][:12]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--verify", action="store_true", help="check what is present; fetch nothing"
    )
    parser.add_argument("--no-repos", action="store_true", help="skip the git repositories")
    parser.add_argument("--no-tools", action="store_true", help="skip kind 'tool' downloads")
    args = parser.parse_args()
    problems = fetch_files(args.verify, tools=not args.no_tools)
    if not args.no_repos:
        problems += fetch_repos(args.verify)
    print("all pins satisfied" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
