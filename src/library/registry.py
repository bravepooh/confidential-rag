"""Source registry: the single list of what the library is allowed to contain."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import yaml

from .schema import Source, SourceError, Tier, Modality

REGISTRY_PATH = Path("library/sources.yaml")


def load(path: Path | str = REGISTRY_PATH) -> list[Source]:
    path = Path(path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("sources", [])
    sources: list[Source] = []
    seen: set[str] = set()
    for entry in entries:
        src = Source(**entry)
        if src.id in seen:
            raise SourceError(f"duplicate source id: {src.id}")
        seen.add(src.id)
        sources.append(src)
    return sources


def save(sources: Iterable[Source], path: Path | str = REGISTRY_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"sources": [s.to_dict() for s in sources]}
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )


def by_modality(sources: Iterable[Source]) -> dict[str, list[Source]]:
    out: dict[str, list[Source]] = {}
    for s in sources:
        out.setdefault(s.modality.value, []).append(s)
    return out


def summarise(sources: list[Source]) -> str:
    lines = [f"{len(sources)} sources"]
    tiers: dict[str, int] = {}
    mods: dict[str, int] = {}
    for s in sources:
        tiers[s.tier.value] = tiers.get(s.tier.value, 0) + 1
        mods[s.modality.value] = mods.get(s.modality.value, 0) + 1
    lines.append("  by tier:     " + ", ".join(f"{k}={v}" for k, v in sorted(tiers.items())))
    lines.append("  by modality: " + ", ".join(f"{k}={v}" for k, v in sorted(mods.items())))
    return "\n".join(lines)
