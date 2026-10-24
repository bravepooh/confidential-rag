"""Split extracted text into retrievable passages that keep their section path.

Chunks are deliberately modest in size. Retrieval feeds several of them into a
prompt alongside an hour-long transcript, and a passage that is too long buries
the one paragraph that actually mattered.

Undersized passages are merged into a neighbour rather than dropped. A short
section is often the most quotable thing in a document (a definition, a named
principle), and silently discarding it would put a hole in the library exactly
where the clearest statement of a concept lives.
"""

from __future__ import annotations

import re

from .schema import Chunk

HEADING = re.compile(r"^(#{1,4})\s+(.*\S)\s*$")
HEBREW = re.compile(r"[֐-׿]")

TARGET_CHARS = 1400   # roughly 250-350 tokens
MAX_CHARS = 2200
MIN_CHARS = 120       # below this a passage is merged into a neighbour
HARD_MIN_CHARS = 25   # below this it is noise (stray nav text, page numbers)


def detect_lang(text: str) -> str:
    hebrew = len(HEBREW.findall(text))
    letters = sum(1 for ch in text if ch.isalpha())
    if letters and hebrew / letters > 0.3:
        return "he"
    return "en"


def _split_paragraphs(text: str) -> list[tuple[str, str]]:
    """Yield (section_path, paragraph) preserving heading context."""
    stack: list[str] = []
    out: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            para = "\n".join(buf).strip()
            if para:
                out.append((" > ".join(stack), para))
            buf.clear()

    for line in text.split("\n"):
        m = HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            del stack[level - 1:]
            stack.append(m.group(2))
            continue
        if not line.strip():
            flush()
        else:
            buf.append(line)
    flush()
    return out


def _pack(pieces: list[str], joiner: str) -> list[str]:
    """Greedily pack pieces up to TARGET_CHARS."""
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for piece in pieces:
        if size + len(piece) > TARGET_CHARS and buf:
            out.append(joiner.join(buf).strip())
            buf, size = [], 0
        buf.append(piece)
        size += len(piece) + len(joiner)
    if buf:
        out.append(joiner.join(buf).strip())
    return [c for c in out if c.strip()]


def _split_long(para: str) -> list[str]:
    """Split an oversized block, cascading through weaker boundaries.

    Sentence splitting alone is not enough for speech. Whisper transcribes
    Hebrew audio as one line per utterance with almost no terminal punctuation
    (measured: 16 periods across 68,000 characters), so a sentence-only split
    left single chunks of ~17,000 characters, which bury the relevant passage
    and blow up the prompt. Session recordings will have exactly this shape, so
    the splitter falls back to line breaks and finally to a word-boundary
    budget, and never emits a block above MAX_CHARS.
    """
    pieces = _pack(re.split(r"(?<=[.!?׃׀])\s+", para), " ")

    # Fall back to line breaks for anything still oversized (speech transcripts).
    refined: list[str] = []
    for piece in pieces:
        if len(piece) <= MAX_CHARS:
            refined.append(piece)
        else:
            refined.extend(_pack(piece.split("\n"), "\n"))

    # Last resort: hard-split on word boundaries so nothing exceeds the cap.
    final: list[str] = []
    for piece in refined:
        if len(piece) <= MAX_CHARS:
            final.append(piece)
            continue
        words = piece.split()
        buf: list[str] = []
        size = 0
        for w in words:
            if size + len(w) + 1 > TARGET_CHARS and buf:
                final.append(" ".join(buf))
                buf, size = [], 0
            buf.append(w)
            size += len(w) + 1
        if buf:
            final.append(" ".join(buf))

    return [c for c in final if c.strip()]


def _blocks(text: str) -> list[tuple[str, str]]:
    """Group paragraphs into (section, body) blocks near TARGET_CHARS."""
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    current_len = 0
    current_section = ""

    def close() -> None:
        nonlocal current, current_len
        if current:
            body = "\n\n".join(current).strip()
            if body:
                blocks.append((current_section, body))
        current = []
        current_len = 0

    for section, para in _split_paragraphs(text):
        if section != current_section:
            close()
            current_section = section

        if len(para) > MAX_CHARS:
            close()
            for piece in _split_long(para):
                blocks.append((current_section, piece))
            continue

        if current_len + len(para) > TARGET_CHARS and current:
            close()

        current.append(para)
        current_len += len(para)

    close()
    return blocks


def _same_family(a: str, b: str) -> bool:
    """True when two section paths belong to the same branch of the document."""
    if a == b:
        return True
    return a.startswith(f"{b} > ") or b.startswith(f"{a} > ")


def _merge_small(blocks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Fold undersized blocks into a neighbour instead of losing them.

    Merging never crosses a section family or a language boundary. A citation
    names a section, so gluing two unrelated sections together would make the
    citation point at text that is not there. A short section that has no
    eligible neighbour simply stays a short chunk, which is fine: a crisp
    two-line definition is worth retrieving on its own.
    """
    kept = [(s, b) for s, b in blocks if len(b) >= HARD_MIN_CHARS]
    if not kept:
        return []

    merged: list[list[str]] = []
    for section, body in kept:
        if merged:
            prev_section, prev_body = merged[-1]
            undersized = len(body) < MIN_CHARS or len(prev_body) < MIN_CHARS
            compatible = _same_family(prev_section, section) and (
                detect_lang(prev_body) == detect_lang(body)
            )
            if undersized and compatible and len(prev_body) + len(body) <= MAX_CHARS:
                merged[-1][1] = f"{prev_body}\n\n{body}"
                continue
        merged.append([section, body])

    return [(s, b) for s, b in merged if len(b) >= HARD_MIN_CHARS]


def chunk_text(source_id: str, text: str) -> list[Chunk]:
    blocks = _merge_small(_blocks(text))
    return [
        Chunk(
            source_id=source_id,
            text=body,
            ordinal=i,
            section=section,
            lang=detect_lang(body),
        )
        for i, (section, body) in enumerate(blocks)
    ]
