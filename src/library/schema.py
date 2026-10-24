"""Core data model for the library.

Provenance is not decoration here. Every chunk that reaches the model carries
enough metadata to answer "where did this come from", because guidance the
therapist cannot trace back to a source is guidance she cannot use.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import Any


class Tier(str, Enum):
    """What we are allowed to store for a source. See docs/sourcing-policy.md."""

    OPEN = "open"                      # open access / CC / public domain: full text
    PUBLIC_WEB = "public_web"          # openly published pages: extract + cite
    ORIGINAL = "original"              # our own synthesis written for this project
    REFERENCE_ONLY = "reference_only"  # copyrighted books: bibliography + our notes
    PRIVATE = "private"                # her material: private box only, never committed


class Modality(str, Enum):
    EFT = "eft"        # Emotionally Focused Therapy
    EFCT = "efct"      # Emotionally Focused Couple Therapy
    IFS = "ifs"        # Internal Family Systems
    PACT = "pact"      # Psychobiological Approach to Couple Therapy
    AEDP = "aedp"      # Accelerated Experiential Dynamic Psychotherapy
    CROSS = "cross"    # attachment theory, affective neuroscience, shared foundations
    PRACTICE = "practice"  # her own training material


class SourceError(ValueError):
    """Raised when a source violates the sourcing policy."""


def slugify(value: str, maxlen: int = 60) -> str:
    value = re.sub(r"[^\w\s-]", "", value.lower())
    value = re.sub(r"[\s_-]+", "-", value).strip("-")
    return value[:maxlen]


@dataclass
class Source:
    """A single item in the library registry."""

    id: str
    title: str
    modality: Modality
    tier: Tier
    url: str | None = None
    authors: list[str] = field(default_factory=list)
    publisher: str | None = None
    year: int | None = None
    isbn: str | None = None
    license: str | None = None
    # Tier C only: structural pointers so guidance can cite a chapter.
    chapters: list[str] = field(default_factory=list)
    # Tier C only: path to our own original concept notes about this work.
    notes_path: str | None = None
    # Populated at fetch time.
    fetched_at: str | None = None
    checksum: str | None = None
    lang: str = "en"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.modality, str):
            self.modality = Modality(self.modality)
        if isinstance(self.tier, str):
            self.tier = Tier(self.tier)
        self.validate()

    def validate(self) -> None:
        if not self.id or not self.title:
            raise SourceError(f"source needs id and title: {self!r}")

        if self.tier in (Tier.OPEN, Tier.PUBLIC_WEB) and not self.url:
            raise SourceError(f"{self.id}: tier {self.tier.value} requires a url")

        if self.tier is Tier.REFERENCE_ONLY:
            # The whole point of this tier: we hold a pointer, not the text.
            # Bibliography is mandatory, because a citation the therapist cannot
            # act on is worthless. Concept notes are optional: without them the
            # entry is still a valid citation target, it just contributes no
            # retrievable passages.
            if not (self.authors and (self.isbn or self.publisher or self.year)):
                raise SourceError(
                    f"{self.id}: reference_only needs authors plus one of "
                    "isbn/publisher/year so the therapist can find the volume"
                )

    @property
    def may_store_body(self) -> bool:
        """Tier C never gets body text ingested. Enforced at ingest time."""
        return self.tier in (Tier.OPEN, Tier.PUBLIC_WEB, Tier.ORIGINAL, Tier.PRIVATE)

    @property
    def citation(self) -> str:
        """Short human-readable citation used in generated guidance."""
        who = ", ".join(self.authors) if self.authors else (self.publisher or "")
        bits = [b for b in (who, self.title, str(self.year) if self.year else "") if b]
        base = ". ".join(bits)
        if self.tier is Tier.REFERENCE_ONLY and self.chapters:
            return base
        if self.url:
            return f"{base} ({self.url})" if base else self.url
        return base

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["modality"] = self.modality.value
        d["tier"] = self.tier.value
        return d


@dataclass
class Chunk:
    """A retrievable passage, carrying its provenance."""

    source_id: str
    text: str
    ordinal: int
    section: str = ""
    lang: str = "en"
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.source_id}:{self.ordinal}:{self.text[:200]}".encode()
            ).hexdigest()[:16]
            self.id = f"{self.source_id}::{self.ordinal:04d}::{digest}"

    @property
    def char_count(self) -> int:
        return len(self.text)

    def payload(self, source: Source) -> dict[str, Any]:
        """Metadata stored alongside the vector, and surfaced in citations."""
        return {
            "chunk_id": self.id,
            "source_id": self.source_id,
            "ordinal": self.ordinal,
            "section": self.section,
            "lang": self.lang,
            "text": self.text,
            "title": source.title,
            "modality": source.modality.value,
            "tier": source.tier.value,
            "url": source.url,
            "citation": source.citation,
            "chapters": source.chapters,
        }


def today() -> str:
    return date.today().isoformat()
