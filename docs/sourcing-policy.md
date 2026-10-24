# Sourcing policy

The couples-therapy literature this system reasons over is, for the most part,
commercially published and copyrighted: Johnson on EFT, Schwartz on IFS, Tatkin
on PACT, Fosha on AEDP, plus institute training manuals. "Publicly available"
is not the same as "free to copy", and a private research library does not
become one by living on our own server.

So the library never becomes a shadow copy of those books. It holds three
different kinds of material, tiered by what we are actually allowed to store.

## Tier A — open

Open-access research articles (PMC, DOAJ, publisher open-access), public-domain
texts, and anything under a CC licence that permits redistribution.

- **Stored:** full text.
- **Retrieval:** full passages.
- **Citation:** normal academic citation with DOI or URL.

This tier is the evidential backbone. A good deal of the EFT outcome research
and a fair amount of the attachment and affective-neuroscience literature that
underpins all five modalities is open access.

## Tier B — public web

Pages published openly by the method organisations and by practising clinicians:
institute descriptions of their own model, public explainer pages, clinician
blog posts and published interviews.

- **Stored:** extracted readable text, with provenance and retrieval date.
- **Retrieval:** passages used as context.
- **In output:** brief quotation only (a sentence or so) with attribution, and a
  link. Never a reproduced page.

These pages are published to be read. We read them, index them for retrieval,
and point back at them. We do not republish them.

## Tier C — reference only

The canonical books and the institute training manuals. Also anything behind a
paywall, and anything whose licence we cannot establish.

- **Stored:** a bibliographic record only — title, author, edition, ISBN,
  chapter and section structure — together with **our own original concept
  notes** written for this project.
- **Retrieval:** our notes are retrievable. The book text is not, because it is
  not there.
- **In output:** "this pattern matches the withdrawer-pursuer cycle; see Johnson,
  *Emotionally Focused Couple Therapy*, ch. 4" — a pointer to the volume the
  therapist already owns and can open.

**This is the tier that matters most, and it is also the better design.** A
clinician verifying a piece of guidance wants the real page in the real book,
not a paraphrase of it from a vector store. Pointing her to her own shelf is
more useful than holding a copy we should not hold.

## Her own material (private tier)

The therapist's own Hebrew training documents are hers. They are ingested only on the private
box, never committed, and never sent to any external service. They sit at the
top of the retrieval priority order, because the whole point of the system is to
reflect the way she was taught to work.

## Rules the ingest enforces

1. Every source carries a `tier` in the registry. There is no default: an
   unclassified source is not ingested.
2. Tier C sources cannot carry body text. The schema rejects it.
3. `robots.txt` is respected on fetch, requests are rate-limited and identified.
4. Every chunk keeps `source_id`, retrieval date and licence, so any sentence in
   any output can be traced back to where it came from.
5. Generated guidance quotes briefly and cites; it never reproduces long
   passages, and the prompt says so explicitly.
