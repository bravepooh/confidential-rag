#!/usr/bin/env python3
"""Transcribe a podcast RSS feed into library/transcripts/ for indexing.

Built for the Hebrew IFS podcast (העולם בפנים), which is the richest Hebrew
IFS material available anywhere; almost everything else in Hebrew on this model
is short explainer pages.

Output is deliberately gitignored. A transcript is a complete derived copy of
a copyrighted recording, so it is indexed locally for retrieval and never
committed; the registry holds the citation so guidance points at the episode.

Usage:
    python scripts/transcribe_podcast.py <rss-url> <id-prefix> [--limit N]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import httpx
from lxml import etree

ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
TRANSCRIPT_DIR = Path("library/transcripts")
WORK_DIR = Path("library/_podcast_work")
MODEL = Path.home() / ".whisper-models" / "ggml-large-v3-turbo.bin"


def episodes(rss_url: str) -> list[dict]:
    xml = httpx.get(rss_url, timeout=60, follow_redirects=True).content
    channel = etree.fromstring(xml).find("channel")
    show = (channel.findtext("title") or "").strip()
    out = []
    for item in reversed(channel.findall("item")):  # oldest first
        enc = item.find("enclosure")
        if enc is None or not enc.get("url"):
            continue
        out.append({
            "show": show,
            "title": (item.findtext("title") or "").strip(),
            "url": enc.get("url"),
            "duration": item.findtext(f"{ITUNES}duration") or "",
            "pubdate": (item.findtext("pubDate") or "")[:16],
            "link": (item.findtext("link") or "").strip(),
        })
    return out


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def transcribe_one(ep: dict, sid: str) -> Path | None:
    dest = TRANSCRIPT_DIR / f"{sid}.md"
    if dest.exists():
        print(f"  skip   {sid} (already transcribed)", flush=True)
        return dest

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    audio = WORK_DIR / f"{sid}.mp3"
    wav = WORK_DIR / f"{sid}.wav"

    try:
        if not audio.exists():
            with httpx.stream("GET", ep["url"], timeout=180, follow_redirects=True) as r:
                r.raise_for_status()
                with open(audio, "wb") as fh:
                    for chunk in r.iter_bytes(1 << 16):
                        fh.write(chunk)

        run(["ffmpeg", "-y", "-v", "error", "-i", str(audio),
             "-vn", "-ac", "1", "-ar", "16000", str(wav)])

        run(["whisper-cli", "-m", str(MODEL), "-l", "he",
             "-f", str(wav), "--output-txt",
             "--output-file", str(WORK_DIR / sid)])

        body = (WORK_DIR / f"{sid}.txt").read_text(encoding="utf-8").strip()
        if len(body) < 400:
            print(f"  FAIL   {sid}: transcript suspiciously short ({len(body)})", flush=True)
            return None

        # One heading so the chunker keeps an episode-level section label.
        header = f"# {ep['title']}\n\n{ep['show']} · {ep['pubdate']} · {ep['duration']}\n\n"
        dest.write_text(header + body + "\n", encoding="utf-8")
        print(f"  ok     {sid}  {len(body):>7} chars  {ep['title'][:44]}", flush=True)
        return dest
    except subprocess.CalledProcessError as exc:
        print(f"  FAIL   {sid}: {exc.cmd[0]} failed", flush=True)
        return None
    except Exception as exc:
        print(f"  FAIL   {sid}: {type(exc).__name__}: {exc}", flush=True)
        return None
    finally:
        for tmp in (audio, wav, WORK_DIR / f"{sid}.txt"):
            tmp.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rss")
    ap.add_argument("prefix")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    eps = episodes(args.rss)
    if args.limit:
        eps = eps[: args.limit]
    print(f"{len(eps)} episodes from {eps[0]['show'] if eps else '?'}\n", flush=True)

    done = 0
    for i, ep in enumerate(eps, start=1):
        sid = f"{args.prefix}-{i:02d}"
        if transcribe_one(ep, sid):
            done += 1
    print(f"\ntranscribed {done}/{len(eps)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
