"""Tests for the library core.

The sourcing-policy guards and the citation-integrity guarantees are the two
things that must never silently regress, so they are tested directly.
"""

from __future__ import annotations

import pytest

from library.chunk import chunk_text, detect_lang
from library.schema import Chunk, Source, SourceError, Tier


# --------------------------------------------------------------------------
# sourcing policy
# --------------------------------------------------------------------------

def test_reference_only_requires_bibliography():
    """A citation the therapist cannot act on is worthless."""
    with pytest.raises(SourceError):
        Source(id="b", title="A Book", modality="eft", tier="reference_only")

    with pytest.raises(SourceError):
        # author but nothing to locate the volume by
        Source(id="b", title="A Book", modality="eft", tier="reference_only",
               authors=["Johnson, Sue"])

    # bibliography alone is enough: it is a valid citation target that simply
    # contributes no retrievable passages
    ok = Source(id="b", title="A Book", modality="eft", tier="reference_only",
                authors=["Johnson, Sue"], year=2019)
    assert ok.tier is Tier.REFERENCE_ONLY
    assert ok.may_store_body is False


def test_reference_only_never_stores_body():
    book = Source(
        id="b", title="A Book", modality="ifs", tier="reference_only",
        authors=["Schwartz, Richard"], year=2021, notes_path="notes.md",
    )
    assert book.may_store_body is False

    page = Source(id="p", title="Page", modality="ifs", tier="public_web",
                  url="https://example.org/a")
    assert page.may_store_body is True


def test_open_and_public_web_require_url():
    with pytest.raises(SourceError):
        Source(id="x", title="Paper", modality="cross", tier="open")


# --------------------------------------------------------------------------
# citation integrity
# --------------------------------------------------------------------------

SAMPLE = """# The Negative Cycle

When partners feel disconnected they often fall into a repeating pattern. One
reaches, the other pulls away. The more one pursues the more the other
withdraws, and each move confirms the other fear until neither finds a way back.

## Recognising the pattern

Naming the cycle as the shared enemy shifts blame away from either partner.

# מעגל הקשר

כאשר בני הזוג חשים ניתוק, הם נופלים לדפוס חוזר. אחד מושיט יד, השני מתרחק.
"""


def test_short_section_is_merged_not_dropped():
    """A two-line definition is often the most quotable thing in a document."""
    chunks = chunk_text("demo", SAMPLE)
    assert any("shared enemy" in c.text for c in chunks)


def test_merging_never_crosses_language():
    chunks = chunk_text("demo", SAMPLE)
    for c in chunks:
        assert not ("shared enemy" in c.text and "כאשר" in c.text)


def test_hebrew_body_survives_and_is_tagged():
    chunks = chunk_text("demo", SAMPLE)
    hebrew = [c for c in chunks if c.lang == "he"]
    assert hebrew, "Hebrew passage must survive chunking"
    assert any("כאשר בני הזוג" in c.text for c in hebrew)


def test_section_label_matches_content():
    """A citation names a section; the text must actually come from it."""
    chunks = chunk_text("demo", SAMPLE)
    for c in chunks:
        if "כאשר בני הזוג" in c.text:
            assert c.section == "מעגל הקשר"
        if "shared enemy" in c.text:
            assert c.section.startswith("The Negative Cycle")


def test_speech_transcript_never_exceeds_max_chunk():
    """Whisper emits one line per utterance with almost no punctuation.

    Real measurement from the Hebrew IFS podcast: 16 periods across 68,000
    characters. A sentence-only splitter produced single 17,000-char chunks.
    Session recordings will look the same, so this must stay fixed.
    """
    from library.chunk import MAX_CHARS

    line = "אז החלק הזה מגיע ומנסה להגן עליה מפני הכאב הישן שהיא נושאת"
    transcript = "# פרק בדיקה\n\n" + "\n".join([line] * 400)  # ~23k chars, 1 period

    chunks = chunk_text("pod", transcript)
    assert len(chunks) > 10, "punctuation-poor speech must still split"
    oversized = [c for c in chunks if c.char_count > MAX_CHARS]
    assert not oversized, f"{len(oversized)} chunks exceeded MAX_CHARS"
    # and nothing was silently dropped
    assert sum(c.char_count for c in chunks) > len(transcript) * 0.9


def test_no_punctuation_at_all_still_splits():
    """A wall of words with zero punctuation must still be chunked."""
    from library.chunk import MAX_CHARS

    wall = " ".join(["מילה"] * 4000)
    chunks = chunk_text("wall", wall)
    assert chunks
    assert all(c.char_count <= MAX_CHARS for c in chunks)


def test_detect_lang():
    assert detect_lang("שלום עולם זהו טקסט בעברית לבדיקה") == "he"
    assert detect_lang("This is an ordinary English sentence about couples.") == "en"


def test_chunk_ids_are_stable_and_unique():
    a = chunk_text("demo", SAMPLE)
    b = chunk_text("demo", SAMPLE)
    assert [c.id for c in a] == [c.id for c in b]
    assert len({c.id for c in a}) == len(a)


# --------------------------------------------------------------------------
# payload carries provenance
# --------------------------------------------------------------------------

def test_payload_carries_citation():
    src = Source(
        id="eft-demo", title="Demo Page", modality="eft", tier="public_web",
        url="https://example.org/eft", authors=["Johnson, Sue"], year=2020,
    )
    chunk = Chunk(source_id="eft-demo", text="x" * 200, ordinal=0, section="Cycle")
    payload = chunk.payload(src)
    assert payload["source_id"] == "eft-demo"
    assert payload["section"] == "Cycle"
    assert payload["tier"] == "public_web"
    assert "example.org" in payload["citation"]
