"""Vector storage on Qdrant, in local file mode (no server needed in dev).

The payload carried with every vector is what makes citation possible: title,
modality, tier, section, url and the chapter pointers for reference-only works.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from qdrant_client import QdrantClient, models

from .schema import Chunk, Source

INDEX_PATH = Path("library/index")
COLLECTION = "library"


def client(path: Path | str = INDEX_PATH) -> QdrantClient:
    Path(path).mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(path))


def ensure_collection(qc: QdrantClient, dim: int, name: str = COLLECTION) -> None:
    existing = {c.name for c in qc.get_collections().collections}
    if name in existing:
        return
    qc.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )


def upsert(
    qc: QdrantClient,
    chunks: list[Chunk],
    vectors: list[list[float]],
    source: Source,
    name: str = COLLECTION,
) -> int:
    if not chunks:
        return 0
    points = [
        models.PointStruct(
            id=abs(hash(chunk.id)) % (2**63),
            vector=vector,
            payload=chunk.payload(source),
        )
        for chunk, vector in zip(chunks, vectors)
    ]
    qc.upsert(collection_name=name, points=points)
    return len(points)


def drop_source(qc: QdrantClient, source_id: str, name: str = COLLECTION) -> None:
    """Remove every chunk of one source, so re-ingest never duplicates."""
    try:
        qc.delete(
            collection_name=name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="source_id",
                            match=models.MatchValue(value=source_id),
                        )
                    ]
                )
            ),
        )
    except Exception:
        pass  # collection may not exist yet


def search(
    qc: QdrantClient,
    vector: list[float],
    limit: int = 8,
    modality: str | None = None,
    name: str = COLLECTION,
) -> list[dict[str, Any]]:
    flt = None
    if modality:
        flt = models.Filter(
            must=[
                models.FieldCondition(
                    key="modality", match=models.MatchValue(value=modality)
                )
            ]
        )
    hits = qc.query_points(
        collection_name=name, query=vector, limit=limit, query_filter=flt
    ).points
    return [{"score": h.score, **(h.payload or {})} for h in hits]


#: Methods the guidance must consider on every session. Order is the reading
#: order from docs / the cross-method map, not a ranking.
CORE_MODALITIES = ("pact", "efct", "eft", "ifs", "aedp")


def search_balanced(
    qc: QdrantClient,
    vector: list[float],
    per_modality: int = 3,
    modalities: tuple[str, ...] = CORE_MODALITIES,
    extra: int = 4,
    name: str = COLLECTION,
) -> list[dict[str, Any]]:
    """Retrieve with a guaranteed slot per method, then fill from the open field.

    Plain top-k does not work for this library and cannot be made to. The
    corpora are wildly uneven (AEDP ~1000 chunks, IFS ~230), and the Hebrew
    material is concentrated in one of them, so a general Hebrew clinical query
    returns the largest corpus almost every time. Measured: a Hebrew query about
    a protective part returned nothing from IFS at all, while the same query
    filtered to IFS returned good passages at a similar score. The content was
    never missing; it was outvoted.

    Since the analysis pass has to read every session against EFT, IFS, PACT and
    AEDP, each method gets its own slot regardless of corpus size. The unfiltered
    remainder still lets a strongly-matching source win on merit.
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    for modality in modalities:
        for hit in search(qc, vector, limit=per_modality, modality=modality, name=name):
            cid = hit.get("chunk_id")
            if cid not in seen:
                seen.add(cid)
                out.append(hit)

    for hit in search(qc, vector, limit=extra + len(seen), name=name):
        if len(out) >= len(modalities) * per_modality + extra:
            break
        cid = hit.get("chunk_id")
        if cid not in seen:
            seen.add(cid)
            out.append(hit)

    out.sort(key=lambda h: h.get("score", 0.0), reverse=True)
    return out


def stats(qc: QdrantClient, name: str = COLLECTION) -> dict[str, Any]:
    existing = {c.name for c in qc.get_collections().collections}
    if name not in existing:
        return {"chunks": 0, "sources": 0, "by_modality": {}, "by_tier": {}}

    count = qc.count(collection_name=name, exact=True).count
    by_mod: dict[str, int] = {}
    by_tier: dict[str, int] = {}
    sources: set[str] = set()

    offset = None
    while True:
        points, offset = qc.scroll(
            collection_name=name,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            pl = p.payload or {}
            by_mod[pl.get("modality", "?")] = by_mod.get(pl.get("modality", "?"), 0) + 1
            by_tier[pl.get("tier", "?")] = by_tier.get(pl.get("tier", "?"), 0) + 1
            sources.add(pl.get("source_id", "?"))
        if offset is None:
            break

    return {
        "chunks": count,
        "sources": len(sources),
        "by_modality": dict(sorted(by_mod.items())),
        "by_tier": dict(sorted(by_tier.items())),
    }
