"""Turn fetched files into clean text with section headings preserved.

Headings matter: they become the `section` on each chunk, which is what lets a
citation say "under 'The Negative Cycle'" instead of just naming the page.
"""

from __future__ import annotations

import re
from pathlib import Path

_WS = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WS.sub(" ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(lines)
    return _BLANKS.sub("\n\n", text).strip()


def from_html(raw: str) -> str:
    """Extract readable body text, marking headings as markdown-style lines."""
    try:
        import trafilatura  # type: ignore

        extracted = trafilatura.extract(
            raw,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            output_format="markdown",
        )
        if extracted and len(extracted) > 200:
            return _tidy(extracted)
    except Exception:
        pass

    # Fallback: BeautifulSoup with heading preservation.
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return _tidy(re.sub(r"<[^>]+>", " ", raw))

    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "form", "noscript"]):
        tag.decompose()

    parts: list[str] = []
    body = soup.body or soup
    for el in body.find_all(["h1", "h2", "h3", "h4", "p", "li", "blockquote"]):
        txt = el.get_text(" ", strip=True)
        if not txt:
            continue
        if el.name in ("h1", "h2", "h3", "h4"):
            level = int(el.name[1])
            parts.append(f"\n{'#' * level} {txt}\n")
        elif el.name == "li":
            parts.append(f"- {txt}")
        else:
            parts.append(txt)
    return _tidy("\n".join(parts))


def from_jats(path: Path) -> str:
    """Extract readable text from a JATS/NLM article XML (PubMed Central).

    Only the article's own front matter and body are taken. The back matter is
    skipped deliberately: it is mostly the reference list, whose cited titles
    would otherwise be indexed as if they were this article's content and
    produce citations pointing at the wrong paper.
    """
    from lxml import etree  # type: ignore

    parser = etree.XMLParser(recover=True, resolve_entities=False, no_network=True)
    tree = etree.parse(str(path), parser)
    root = tree.getroot()

    article = root if root.tag == "article" else root.find(".//article")
    if article is None:
        return ""

    def text_of(el) -> str:
        return _tidy(" ".join(el.itertext()))

    parts: list[str] = []

    title_el = article.find(".//front//article-title")
    if title_el is not None:
        parts.append(f"# {text_of(title_el)}")

    for abstract in article.findall(".//front//abstract"):
        label = abstract.get("abstract-type") or "Abstract"
        parts.append(f"\n## {label.title()}\n")
        for p in abstract.iter("p"):
            txt = text_of(p)
            if txt:
                parts.append(txt)

    body = article.find("body")
    if body is not None:
        def walk(sec, depth: int = 2) -> None:
            title = sec.find("title")
            if title is not None:
                t = text_of(title)
                if t:
                    parts.append(f"\n{'#' * min(depth, 4)} {t}\n")
            for child in sec:
                if child.tag == "sec":
                    walk(child, depth + 1)
                elif child.tag in ("p", "list", "disp-quote"):
                    txt = text_of(child)
                    if txt:
                        parts.append(txt)

        for child in body:
            if child.tag == "sec":
                walk(child)
            elif child.tag in ("p", "list", "disp-quote"):
                txt = text_of(child)
                if txt:
                    parts.append(txt)

    return _tidy("\n\n".join(parts))


def from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("pypdf is required to read PDFs") from exc

    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            pages.append(f"\n## page {i}\n{txt}")
    return _tidy("\n".join(pages))


def from_docx(path: Path) -> str:
    """Used only on the private box, for the therapist's own training documents."""
    try:
        import docx  # type: ignore
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("python-docx is required to read .docx") from exc

    document = docx.Document(str(path))
    parts: list[str] = []
    for para in document.paragraphs:
        txt = (para.text or "").strip()
        if not txt:
            continue
        style = (para.style.name or "").lower() if para.style else ""
        if style.startswith("heading"):
            digits = [c for c in style if c.isdigit()]
            level = int(digits[0]) if digits else 2
            parts.append(f"\n{'#' * max(1, min(level, 4))} {txt}\n")
        else:
            parts.append(txt)
    return _tidy("\n".join(parts))


def from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return from_jats(path)
    if suffix in (".html", ".htm"):
        return from_html(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".pdf":
        return from_pdf(path)
    if suffix == ".docx":
        return from_docx(path)
    if suffix in (".md", ".txt"):
        return _tidy(path.read_text(encoding="utf-8", errors="ignore"))
    raise ValueError(f"unsupported file type: {path}")
