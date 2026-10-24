"""The confidentiality boundary, tested in code rather than trusted in docs.

Private material (the therapist's documents, session audio, transcripts) must be impossible to
ingest by accident, and impossible to commit.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from library import ingest
from library.schema import Source

ROOT = Path(__file__).resolve().parent.parent


def test_private_tier_is_refused_without_explicit_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "CURATED_DIR", tmp_path)
    (tmp_path / "p1.md").write_text("confidential " * 50, encoding="utf-8")
    src = Source(id="p1", title="Training doc", modality="practice", tier="private")

    text, skip = ingest.text_for(src)
    assert text == "" and "allow-private" in skip

    text, skip = ingest.text_for(src, allow_private=True)   # only on the private box
    assert skip is None and "confidential" in text


def test_reference_only_never_reads_the_book(tmp_path, monkeypatch):
    """Even if a copy of the book text exists on disk, only our own notes are read."""
    monkeypatch.setattr(ingest, "CURATED_DIR", tmp_path)
    (tmp_path / "book.md").write_text("BOOK TEXT " * 50, encoding="utf-8")
    notes = tmp_path / "notes.md"
    notes.write_text("our own concept notes " * 20, encoding="utf-8")
    src = Source(id="book", title="A Book", modality="ifs", tier="reference_only",
                 authors=["Author, A."], year=2020, notes_path=str(notes))

    text, skip = ingest.text_for(src)
    assert skip is None
    assert "BOOK TEXT" not in text and "concept notes" in text


def test_repo_boundary_check_passes():
    """scripts/check_boundary.py is the same check CI runs before anything is published."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_boundary.py")],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
