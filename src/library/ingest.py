"""Ingest pipeline: registry -> fetch -> extract -> chunk -> embed -> store.

The sourcing policy is enforced here, not merely documented:
  - reference_only sources never contribute body text. What gets indexed for
    them is our own concept notes file, which is original writing.
  - private sources are refused unless explicitly enabled, so her material can
    never be indexed by accident on a laptop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import embed, extract, fetch, store
from .chunk import chunk_text
from .schema import Chunk, Source, Tier

CURATED_DIR = Path("library/sources/curated")
PUBLIC_DIR = Path("library/sources/public")
PRIVATE_DIR = Path("library/sources/private")

#: Transcripts we generated from published audio. Indexed for retrieval, but
#: gitignored and never committed: a transcript is a complete derived copy of
#: someone's copyrighted recording, which is a bigger step than indexing a page
#: that was already published as text. The registry keeps the citation so
#: guidance points listeners at the real episode.
TRANSCRIPT_DIR = Path("library/transcripts")


@dataclass
class IngestResult:
    source_id: str
    chunks: int
    skipped: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped is None


def text_for(source: Source, allow_private: bool = False) -> tuple[str, str | None]:
    """Return (text, skip_reason). Empty text plus a reason means skip."""

    if source.tier is Tier.PRIVATE and not allow_private:
        return "", "private tier requires --allow-private (run only on the box)"

    if source.tier is Tier.REFERENCE_ONLY:
        # Never the book. Only our own notes about it, if we wrote any.
        # Without notes the entry stays a citation target and indexes nothing.
        if not source.notes_path:
            return "", "bibliography only (citation target, no passages)"
        notes = Path(source.notes_path)
        if not notes.exists():
            return "", f"bibliography only (notes not written: {notes})"
        return extract.from_path(notes), None

    # Tier A / B / original / private: prefer a locally authored or generated
    # file, else the fetched raw file.
    transcript = TRANSCRIPT_DIR / f"{source.id}.md"
    if transcript.exists():
        return extract.from_path(transcript), None

    curated = CURATED_DIR / f"{source.id}.md"
    if curated.exists():
        return extract.from_path(curated), None

    if source.tier is Tier.ORIGINAL:
        # Our own synthesis has no upstream to fetch; the file simply must exist.
        return "", f"original note not written yet: {curated}"

    raw = fetch.raw_path(source)
    if not raw.exists():
        return "", "not fetched yet"
    try:
        return extract.from_html(raw.read_text(encoding="utf-8", errors="ignore")) \
            if raw.suffix in (".html", ".htm") else extract.from_path(raw), None
    except Exception as exc:
        return "", f"extract failed: {exc}"


def build_chunks(source: Source, allow_private: bool = False) -> tuple[list[Chunk], str | None]:
    text, skip = text_for(source, allow_private=allow_private)
    if skip:
        return [], skip
    if len(text) < 200:
        return [], "extracted text too short to be useful"
    chunks = chunk_text(source.id, text)
    if not chunks:
        return [], "no chunks produced"
    return chunks, None


def ingest(
    sources: list[Source],
    allow_private: bool = False,
    model_name: str = embed.DEFAULT_MODEL,
    index_path: Path = store.INDEX_PATH,
) -> list[IngestResult]:
    qc = store.client(index_path)
    store.ensure_collection(qc, embed.dimension(model_name))

    results: list[IngestResult] = []
    for source in sources:
        chunks, skip = build_chunks(source, allow_private=allow_private)
        if skip:
            results.append(IngestResult(source.id, 0, skip))
            continue
        vectors = embed.embed_passages([c.text for c in chunks], model_name=model_name)
        store.drop_source(qc, source.id)  # idempotent re-ingest
        n = store.upsert(qc, chunks, vectors, source)
        results.append(IngestResult(source.id, n))
    return results
