# confidential-rag

[![ci](https://github.com/bravepooh/confidential-rag/actions/workflows/ci.yml/badge.svg)](https://github.com/bravepooh/confidential-rag/actions/workflows/ci.yml)

A retrieval library for a session-guidance system built for a single couples therapist, where the
data is confidential health information and **nothing clinical may ever reach a third-party AI
service**. All inference runs on local open-weight models. Every passage that reaches the model
carries its source, so every observation in the output can be traced back and checked.

This repository is the **public half**: the code, the sourcing policy, the security design, and the
registry of public literature. The private half (the therapist's own training documents, session
recordings, transcripts and generated guidance) exists only on a machine in the therapist's custody
and is never committed. CI fails if any of it ever appears here.

## The confidentiality boundary

| Zone | Contents | Where it may be processed |
|---|---|---|
| **Public** (this repo) | Code, method-literature registry (EFT, EFCT, IFS, PACT, AEDP), our own concept notes | Anywhere |
| **Private** | The therapist's training documents, session audio, transcripts, guidance | Local box only, local models only, never committed |

Enforced three ways, not just documented:

1. **In code.** The private tier is refused at ingest unless `--allow-private` is passed, which is
   only done on the private box ([`ingest.py`](src/library/ingest.py)).
2. **In `.gitignore`.** A confidentiality block anchored at the repo root
   ([`.gitignore`](.gitignore)).
3. **In CI.** [`scripts/check_boundary.py`](scripts/check_boundary.py) fails the build if git tracks
   any document, audio or subtitle file, anything under a private path, or a private-tier registry
   entry. A test checks the guard itself.

## Library tiers: copyright as a schema rule

The method literature is mostly copyrighted, so the library never holds copies of books. Each
source carries a tier, and the schema refuses what a tier may not hold
([`docs/sourcing-policy.md`](docs/sourcing-policy.md), [`schema.py`](src/library/schema.py)):

| Tier | What | Stored | In output |
|---|---|---|---|
| A · open | Open-access papers, CC-licensed text | Full text | Normal citation |
| B · public web | Institute and clinician pages | Extracted text, for retrieval | Brief quote, attribution, link |
| C · reference only | The canonical books | Bibliography and chapter pointers, plus our own concept notes. Never the book | "See Johnson, ch. 4": the volume the therapist already owns |
| O · original | Our own synthesis notes | Full text | Cited as ours |
| P · private | The therapist's material | Private box only | Highest retrieval priority |

The registry ([`library/sources.yaml`](library/sources.yaml)) lists **189 public sources** with
provenance; the catalogue ([`docs/SOURCES.md`](docs/SOURCES.md)) shows **5,099 indexed passages**.
The fetched page text and podcast transcripts are rebuilt locally from the registry and are not in
this repo: they are copies of other people's work.

## Pipeline

```
  therapist's phone
     |  Tailscale only, no public port
     v
  upload page -> queue
                   |
            [1] transcribe     ivrit.ai whisper-large-v3-turbo (Hebrew)
            [2] diarize        pyannote: therapist / partner A / partner B
            [3] retrieve       BGE-M3 embeddings, Qdrant, per-method balanced
            [4] analyse        DictaLM 3.0 (Hebrew-native, open weights), multi-pass
            [5] render         Hebrew guidance, every observation cited
                   |
                   v
     encrypted local archive -> rclone crypt -> offsite ciphertext
```

Runs as an overnight batch on CPU: speed is negotiable, quality is not, so the time budget buys a
bigger model and several analysis passes (segment summaries, session arc, method mapping, then a
self-critique pass that drops anything not supported by a retrieved source). There is no training
step: a few dozen documents is far too little to fine-tune on, and retrieval gives the citations a
clinician needs to verify the output.

Threat model and controls (intake, archive, egress allowlist, disk encryption, pseudonymous couple
codes, audio deleted after transcription, consent and DPIA): [`docs/security.md`](docs/security.md).

## What was measured

**Plain top-k retrieval fails on an uneven library, so retrieval is balanced per method.** The
corpora are very uneven (when this was measured, AEDP had about 1,000 passages and IFS about 230),
and most of the Hebrew material sits in one of them. A Hebrew query about a protective part returned nothing from IFS at
all, while the same query filtered to IFS returned good passages at a similar score. The content
was there; it was outvoted. `search_balanced` gives each method a guaranteed slot and lets the open
field fill the rest ([`store.py`](src/library/store.py)).

**Hebrew speech transcripts break sentence-based chunking.** Whisper output from a Hebrew podcast
had 16 periods in 68,000 characters, so a sentence splitter produced single 17,000-character chunks.
The chunker cascades through weaker boundaries down to word level, and a test pins it
([`chunk.py`](src/library/chunk.py), [`tests/test_library.py`](tests/test_library.py)). Session
recordings will look the same.

**One embedding space for two languages.** The therapist's material is Hebrew, the literature is
mostly English. BGE-M3 puts both in one vector space, so a Hebrew description of a pursue-withdraw
cycle retrieves the English negative-cycle paper directly, with no translation step.

**Fetching is polite and refuses bot walls.** `robots.txt` is respected, requests are rate-limited
and identified, and a challenge page fails loudly instead of being indexed as content
([`fetch.py`](src/library/fetch.py)).

## Status

| # | Phase | Status |
|---|---|---|
| 0 | Repo, plan, confidentiality boundary | done |
| 1 | Library infrastructure: schema, registry, fetch, extract, chunk, embed, store, CLI | done |
| 2 | Public corpus: 189 sources, 5,099 passages, bilingual retrieval verified | done |
| 3 | Private corpus ingest (private box only) | next |
| 4 | Transcription and diarization | prototype (`scripts/transcribe_feed.py`, used on public podcasts) |
| 5 | Multi-pass analysis engine | designed |
| 6 | Intake and encrypted archive | designed |
| 7 | Calibration: the therapist grades output on past sessions | planned |
| 8 | Hardening: disk encryption, egress allowlist, audit log | planned |

## Usage

```bash
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
python -m pytest tests/ -q

python -m library.cli sources                       # what is registered, by tier
python -m library.cli fetch                         # pull tier A/B into library/raw (local only)
python -m library.cli build                         # extract, chunk, embed, index
python -m library.cli search "withdrawer pursuer" --balanced
python -m library.cli catalog                       # regenerate docs/SOURCES.md
```

On the private box only: `python -m library.cli build --allow-private`.

## Layout

```
library/
  sources.yaml            registry: every public source, with its tier and provenance
  sources/curated/        our own concept notes (tier O, and notes for tier C books)
  sources/private/        the therapist's material          [never committed]
  raw/, transcripts/      fetched third-party text          [rebuilt locally, never committed]
  index/                  Qdrant vectors                     [rebuilt locally]
src/library/
  schema.py               Source, Chunk, Tier; policy guards
  registry.py             load and validate sources.yaml
  fetch.py                polite fetching (robots, rate limit, bot-wall detection, PMC API)
  extract.py              html / JATS / pdf / docx to text with headings
  chunk.py                section- and language-aware chunking
  embed.py                BGE-M3, one vector space for Hebrew and English
  store.py                Qdrant local mode, balanced per-method retrieval
  ingest.py               pipeline; enforces the tier policy
  cli.py                  command line
scripts/
  check_boundary.py       CI guard: nothing private is tracked
  transcribe_feed.py      podcast feed to local transcripts (whisper.cpp)
```
