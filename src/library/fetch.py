"""Polite fetching of Tier A / Tier B sources into library/raw/.

Rules enforced here:
  - robots.txt is respected
  - requests are rate-limited and carry an identifying user agent
  - Tier C (reference_only) is never fetched; there is nothing to fetch
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.robotparser as robotparser
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .schema import Source, Tier, today

RAW_DIR = Path("library/raw")
USER_AGENT = (
    "confidential-rag-library/0.1 (private clinical reference index; "
    "contact: repository owner)"
)
MIN_INTERVAL = 2.0  # seconds between requests to the same host

_last_hit: dict[str, float] = {}
_robots_cache: dict[str, robotparser.RobotFileParser] = {}


# Documented, public APIs meant to be called by software. robots.txt is a
# convention addressed to crawlers indexing web pages; these hosts publish an
# API contract with its own usage policy (rate limits, client identification),
# and the publisher's explicit preference is that software use the API rather
# than scrape the rendered site. We honour the API's own rate limits instead.
#
# This is a narrow allowlist of endpoints verified to be documented APIs. It is
# NOT a mechanism for getting past bot protection: any host that answers with a
# CAPTCHA or challenge page is treated as a hard failure (see looks_like_challenge).
API_ALLOWLIST = {
    "eutils.ncbi.nlm.nih.gov",  # NCBI E-utilities, PMC open-access full text
}


def _robots_allows(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc in API_ALLOWLIST:
        return True
    root = f"{parsed.scheme}://{parsed.netloc}"
    rp = _robots_cache.get(root)
    if rp is None:
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{root}/robots.txt")
        try:
            rp.read()
        except Exception:
            # No reachable robots.txt: treat as permissive, standard behaviour.
            rp.parse([])
        _robots_cache[root] = rp
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    last = _last_hit.get(host)
    if last is not None:
        wait = MIN_INTERVAL - (time.time() - last)
        if wait > 0:
            time.sleep(wait)
    _last_hit[host] = time.time()


PMC_ID = re.compile(r"/(PMC\d+)", re.IGNORECASE)

# Markers that mean we were served a bot wall rather than the document. Storing
# one of these silently would poison the library with challenge-page text, so a
# fetch that hits one fails loudly instead.
#: Markers that only ever appear on an actual interstitial.
STRONG_CHALLENGE_MARKERS = (
    "recaptcha/challengepage",
    "unusual traffic from your computer",
    "/cdn-cgi/challenge-platform",
    "checking your browser before accessing",
    "please verify you are a human",
)

#: Markers that also appear innocently on real pages. A contact form with a
#: captcha widget is not a bot wall, so these only count when the page carries
#: almost no readable text of its own.
WEAK_CHALLENGE_MARKERS = (
    "g-recaptcha",
    "just a moment",
    "enable javascript and cookies",
)

#: Below this much visible text, a page with a weak marker is a wall, not content.
MIN_REAL_TEXT = 1500


def pmc_id(url: str) -> str | None:
    """Return the PMCID if this is a PubMed Central article URL."""
    if "ncbi.nlm.nih.gov" not in url:
        return None
    m = PMC_ID.search(url)
    return m.group(1).upper() if m else None


def effective_url(url: str) -> str:
    """Prefer an official API over scraping a rendered page.

    PubMed Central serves a CAPTCHA to automated clients, and defeating that is
    both prohibited and unnecessary: NCBI publishes E-utilities precisely so
    that software can retrieve open-access full text. Use the documented door.
    """
    pid = pmc_id(url)
    if pid:
        return (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            f"?db=pmc&id={pid}&retmode=xml&tool=confidential-rag-library"
        )
    return url


def visible_text_length(html: str) -> int:
    stripped = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    stripped = re.sub(r"<[^>]+>", " ", stripped)
    return len(re.sub(r"\s+", " ", stripped).strip())


def looks_like_challenge(data: bytes) -> bool:
    """True only when the response really is a bot wall rather than content.

    An earlier version flagged any page containing "g-recaptcha", which wrongly
    rejected a legitimate Hebrew clinical article that merely had a captcha on
    its contact form. Weak markers now require the page to be nearly empty of
    readable text before they count.
    """
    text = data[:200000].decode("utf-8", errors="ignore")
    low = text.lower()

    if any(m in low for m in STRONG_CHALLENGE_MARKERS):
        return True
    if any(m in low for m in WEAK_CHALLENGE_MARKERS):
        return visible_text_length(text) < MIN_REAL_TEXT
    return False


def raw_path(source: Source) -> Path:
    url = source.url or ""
    if pmc_id(url):
        return RAW_DIR / f"{source.id}.xml"
    suffix = ".pdf" if url.lower().endswith(".pdf") else ".html"
    return RAW_DIR / f"{source.id}{suffix}"


def fetch(source: Source, force: bool = False, timeout: float = 30.0) -> Path | None:
    """Fetch one source to library/raw/. Returns the path, or None if skipped."""
    if source.tier is Tier.REFERENCE_ONLY:
        return None  # by design: we hold a citation, not the work
    if source.tier is Tier.PRIVATE:
        return None  # private material is placed by hand on the box
    if not source.url:
        return None

    dest = raw_path(source)
    if dest.exists() and not force:
        return dest

    url = effective_url(source.url)

    if not _robots_allows(url):
        raise PermissionError(f"{source.id}: robots.txt disallows {url}")

    _throttle(url)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en,he;q=0.8"},
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.content

    if looks_like_challenge(data):
        # Never store a bot wall as if it were the document.
        raise RuntimeError(
            f"{source.id}: served a bot-challenge page, not content. "
            "Find an official API or an alternate open host; do not bypass."
        )

    dest.write_bytes(data)
    source.fetched_at = today()
    source.checksum = hashlib.sha256(data).hexdigest()[:16]
    return dest
