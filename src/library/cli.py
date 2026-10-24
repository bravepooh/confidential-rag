"""Command line for the library.

    python -m library.cli sources          # what is registered
    python -m library.cli fetch            # pull tier A/B sources to library/raw
    python -m library.cli build            # extract, chunk, embed, index
    python -m library.cli search "query"   # retrieve with citations
    python -m library.cli stats            # what is in the index
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import embed, ingest, registry, store
from .schema import Tier

# Single-letter tier marker for listings. Kept derived from the enum so a new
# tier can never silently break the listing again.
TIER_MARK = {
    Tier.OPEN.value: "A",
    Tier.PUBLIC_WEB.value: "B",
    Tier.REFERENCE_ONLY.value: "C",
    Tier.ORIGINAL.value: "O",
    Tier.PRIVATE.value: "P",
}


def cmd_sources(args: argparse.Namespace) -> int:
    sources = registry.load(args.registry)
    if not sources:
        print(f"no sources registered in {args.registry}")
        return 0
    print(registry.summarise(sources))
    print()
    for mod, items in sorted(registry.by_modality(sources).items()):
        print(f"[{mod}]")
        for s in items:
            mark = TIER_MARK.get(s.tier.value, "?")
            print(f"  ({mark}) {s.id:<44} {s.title[:60]}")
        print()
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    sources = registry.load(args.registry)
    targets = [s for s in sources if s.tier in (Tier.OPEN, Tier.PUBLIC_WEB)]
    if args.only:
        targets = [s for s in targets if s.id in set(args.only)]

    ok = failed = skipped = 0
    for s in targets:
        try:
            path = fetch_one(s, force=args.force)
            if path is None:
                skipped += 1
                print(f"  skip  {s.id}")
            else:
                ok += 1
                size = path.stat().st_size // 1024
                print(f"  ok    {s.id}  ({size} KB)")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {s.id}: {type(exc).__name__}: {exc}")

    # Fetch state goes to a sidecar, never back into sources.yaml. Round-tripping
    # the registry through the YAML dumper silently destroys the hand-written
    # comments and quoting that document the tier policy, which is the one thing
    # in this repo a human most needs to read.
    save_fetch_state(targets, Path(args.registry).parent / "fetch-state.json")
    print(f"\nfetched {ok}, skipped {skipped}, failed {failed}")
    return 0 if failed == 0 else 1


def fetch_one(source, force: bool = False):
    from . import fetch as fetch_mod

    return fetch_mod.fetch(source, force=force)


def save_fetch_state(sources, path: Path) -> None:
    """Record when each source was fetched, alongside the registry, not inside it."""
    import json

    state = {}
    if path.exists():
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    for s in sources:
        if s.fetched_at or s.checksum:
            state[s.id] = {"fetched_at": s.fetched_at, "checksum": s.checksum}
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def cmd_build(args: argparse.Namespace) -> int:
    sources = registry.load(args.registry)
    if args.only:
        sources = [s for s in sources if s.id in set(args.only)]
    if args.modality:
        sources = [s for s in sources if s.modality.value == args.modality]

    if not args.allow_private:
        sources = [s for s in sources if s.tier is not Tier.PRIVATE]

    print(f"building index over {len(sources)} sources "
          f"(model={args.model}, private={'yes' if args.allow_private else 'no'})\n")

    results = ingest.ingest(
        sources,
        allow_private=args.allow_private,
        model_name=args.model,
        index_path=Path(args.index),
    )

    total = 0
    for r in results:
        if r.ok:
            total += r.chunks
            print(f"  ok    {r.source_id:<44} {r.chunks} chunks")
        else:
            print(f"  skip  {r.source_id:<44} {r.skipped}")

    print(f"\nindexed {total} chunks from {sum(1 for r in results if r.ok)} sources")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    qc = store.client(Path(args.index))
    vector = embed.embed_query(args.query, model_name=args.model)
    if args.balanced:
        hits = store.search_balanced(qc, vector, per_modality=args.per_modality)
    else:
        hits = store.search(qc, vector, limit=args.limit, modality=args.modality)
    if not hits:
        print("no results (is the index built?)")
        return 1

    for i, hit in enumerate(hits, start=1):
        print(f"\n{'=' * 78}")
        print(f"[{i}] score {hit['score']:.3f}  |  {hit.get('modality')}  |  "
              f"tier {hit.get('tier')}")
        print(f"    {hit.get('title')}")
        if hit.get("section"):
            print(f"    section: {hit['section']}")
        if hit.get("citation"):
            print(f"    cite: {hit['citation']}")
        print(f"{'-' * 78}")
        text = hit.get("text", "")
        print(text[: args.chars] + ("..." if len(text) > args.chars else ""))
    print()
    return 0


MODALITY_LABEL = {
    "eft": "EFT — Emotionally Focused Therapy",
    "efct": "EFCT — Emotionally Focused Couple Therapy",
    "ifs": "IFS — Internal Family Systems (incl. IFIO for couples)",
    "pact": "PACT — Psychobiological Approach to Couple Therapy",
    "aedp": "AEDP — Accelerated Experiential Dynamic Psychotherapy",
    "cross": "Cross-cutting foundations — attachment, co-regulation, neuroscience",
    "practice": "Her own training material (private box only)",
}

TIER_LABEL = {
    "open": "A · open access, full text stored",
    "public_web": "B · openly readable, indexed for retrieval, quote briefly",
    "original": "O · our own synthesis written for this project",
    "reference_only": "C · copyrighted book, citation pointer only",
    "private": "P · her material, private box only",
}


def cmd_catalog(args: argparse.Namespace) -> int:
    """Write a human-readable catalogue of everything in the library."""
    sources = registry.load(args.registry)
    registered = {s.id for s in sources}
    counts: dict[str, int] = {}
    try:
        qc = store.client(Path(args.index))
        offset = None
        while True:
            points, offset = qc.scroll(
                collection_name=store.COLLECTION, limit=1024,
                offset=offset, with_payload=True, with_vectors=False,
            )
            for p in points:
                sid = (p.payload or {}).get("source_id")
                if sid in registered:
                    counts[sid] = counts.get(sid, 0) + 1
            if offset is None:
                break
    except Exception:
        pass

    by_mod = registry.by_modality(sources)
    lines: list[str] = []
    lines.append("# Library catalogue\n")
    lines.append(
        f"{len(sources)} sources, {sum(counts.values())} indexed passages. "
        "Regenerate with `python -m library.cli catalog`.\n"
    )
    lines.append("Tiers (see `docs/sourcing-policy.md`):\n")
    for t, label in TIER_LABEL.items():
        lines.append(f"- **{label}**")
    lines.append("")

    lines.append("## Summary\n")
    lines.append("| Area | Sources | Passages |")
    lines.append("|---|---:|---:|")
    for mod, items in sorted(by_mod.items(), key=lambda kv: -sum(counts.get(s.id, 0) for s in kv[1])):
        ch = sum(counts.get(s.id, 0) for s in items)
        lines.append(f"| {MODALITY_LABEL.get(mod, mod)} | {len(items)} | {ch} |")
    lines.append(f"| **Total** | **{len(sources)}** | **{sum(counts.values())}** |")
    lines.append("")

    for mod, items in sorted(by_mod.items()):
        ch = sum(counts.get(s.id, 0) for s in items)
        lines.append(f"\n## {MODALITY_LABEL.get(mod, mod)}\n")
        lines.append(f"{len(items)} sources, {ch} passages.\n")
        for tier in ("original", "open", "public_web", "reference_only", "private"):
            group = [s for s in items if s.tier.value == tier]
            if not group:
                continue
            lines.append(f"\n**{TIER_LABEL[tier]}** ({len(group)})\n")
            for s in sorted(group, key=lambda x: -counts.get(x.id, 0)):
                n = counts.get(s.id, 0)
                who = ", ".join(s.authors[:2]) if s.authors else (s.publisher or "")
                bits = [b for b in (who, str(s.year) if s.year else "") if b]
                meta = " · ".join(bits)
                mark = f"{n} passages" if n else "not indexed"
                title = s.title.replace("|", "/")
                if s.url:
                    lines.append(f"- [{title}]({s.url})  \n  {meta} · {mark}")
                else:
                    isbn = f" · ISBN {s.isbn}" if s.isbn else ""
                    lines.append(f"- **{title}**  \n  {meta}{isbn} · {mark}")
            lines.append("")

    not_indexed = [s for s in sources if not counts.get(s.id) and s.tier.value != "reference_only"]
    if not_indexed:
        lines.append("\n## Registered but not indexed\n")
        lines.append(
            "These remain citation targets the therapist can open; their sites "
            "disallow automated access, so we respect that and do not index them.\n"
        )
        for s in sorted(not_indexed, key=lambda x: x.modality.value):
            lines.append(f"- [{s.title}]({s.url}) — {s.modality.value}")
        lines.append("")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out} ({len(sources)} sources, {sum(counts.values())} passages)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    qc = store.client(Path(args.index))
    s = store.stats(qc)
    print(f"chunks:  {s['chunks']}")
    print(f"sources: {s['sources']}")
    print(f"by modality: {s['by_modality']}")
    print(f"by tier:     {s['by_tier']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="library", description="confidential-rag library")
    p.add_argument("--registry", default="library/sources.yaml")
    p.add_argument("--index", default="library/index")
    p.add_argument("--model", default=embed.DEFAULT_MODEL)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("sources", help="list registered sources")
    sp.set_defaults(func=cmd_sources)

    sp = sub.add_parser("fetch", help="fetch tier A/B sources")
    sp.add_argument("--only", nargs="*", help="limit to these source ids")
    sp.add_argument("--force", action="store_true", help="refetch even if cached")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("build", help="extract, chunk, embed and index")
    sp.add_argument("--only", nargs="*")
    sp.add_argument("--modality")
    sp.add_argument("--allow-private", action="store_true",
                    help="ingest private tier (run only on the private box)")
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("search", help="retrieve passages with citations")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=6)
    sp.add_argument("--modality")
    sp.add_argument("--chars", type=int, default=600)
    sp.add_argument("--balanced", action="store_true",
                    help="guarantee a slot per method (use for session analysis)")
    sp.add_argument("--per-modality", type=int, default=3,
                    help="passages per method when --balanced")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("catalog", help="write a readable catalogue of all sources")
    sp.add_argument("--out", default="docs/SOURCES.md")
    sp.set_defaults(func=cmd_catalog)

    sp = sub.add_parser("stats", help="index contents")
    sp.set_defaults(func=cmd_stats)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # Piping into head/less closes stdout early; that is not an error.
        # Point stdout at devnull so interpreter shutdown does not try to flush
        # a closed pipe and print a traceback over the user's output.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        os._exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
