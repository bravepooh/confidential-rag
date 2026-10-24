#!/usr/bin/env python3
"""Fail if anything on the private side of the boundary is tracked by git.

Runs in CI on every push. Checks the files git tracks (not the working tree, which on the
private box legitimately holds private material):
  - no document, audio or subtitle files (the therapist's docs, session recordings, transcripts)
  - nothing under the private paths named in .gitignore
  - no registry entry with tier: private
  - the confidentiality block in .gitignore is still present
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BANNED_EXT = {".docx", ".doc", ".wav", ".mp3", ".m4a", ".mp4", ".srt"}
BANNED_PREFIX = ("library/sources/private/", "sessions/", "transcripts/", "audio/", "guidance/",
                 "library/raw/", "library/transcripts/", "library/index/")
GITIGNORE_MUST_HAVE = ("library/sources/private/", "/sessions/", "/transcripts/", "/audio/",
                       "/guidance/", "*.docx")


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:          # not a git checkout (e.g. a source tarball): check the tree
        return [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
                if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts]
    return out.stdout.splitlines()


def main() -> int:
    problems: list[str] = []
    for f in tracked():
        if Path(f).suffix.lower() in BANNED_EXT:
            problems.append(f"tracked private-type file: {f}")
        if f.startswith(BANNED_PREFIX):
            problems.append(f"tracked file under a private path: {f}")

    reg = ROOT / "library" / "sources.yaml"
    if reg.exists():
        for n, line in enumerate(reg.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*tier:\s*private\s*$", line):
                problems.append(f"library/sources.yaml:{n}: private-tier entry in the public registry")

    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for rule in GITIGNORE_MUST_HAVE:
        if rule not in gi.splitlines():
            problems.append(f".gitignore lost its confidentiality rule: {rule}")

    for p in problems:
        print("BOUNDARY:", p)
    print(f"boundary check: {'FAIL' if problems else 'ok'} ({len(tracked())} tracked files)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
