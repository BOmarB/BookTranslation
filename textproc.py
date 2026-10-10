"""
Shared text cleaning and block chunking for the book pipeline.

Cleaning is deliberately non-destructive and per-page:
  1. dehyphenate       - fixes hyphen line-wraps ("jour-\\nney" -> "journey")
                        so MT never sees a fake word.
  2. strip_page_numbers- drops bare page-number lines at the top/bottom of a
                        page before text is collapsed into paragraphs.
  3. strip_running_headers - removes short repeated book-title header/footer
                        lines (e.g. a title on every page) BEFORE collapse so
                        they can't glue into the page's first sentence.
  4. collapse_wrapped  - squashes visual line wraps into paragraph text.
  5. chunk_text        - splits a page on paragraph/sentence boundaries so no
                        call starts or ends mid-word or mid-thought.

Pages are translated SEPARATELY (not merged) so every MT call stays small and
coherent, and output keeps one page per input page. Running headers are kept
so real chapter/section titles are never destroyed.
"""

from __future__ import annotations

import re

DEFAULT_BLOCK = 4500


def dehyphenate(text: str) -> str:
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = text.replace("\u00ad\n", "")
    return text


def _collapse_wrapped_lines(text: str) -> str:
    paras = re.split(r"\n{2,}", text)
    paras = [re.sub(r"\s*\n\s*", " ", p).strip() for p in paras]
    return "\n\n".join(p for p in paras if p)


def _is_page_number(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.fullmatch(r"\d{1,4}", s):
        return True
    if re.fullmatch(r"[-–—·.]?[\s\d]{1,6}[-–—·.]?", s) and re.search(r"\d", s):
        return True
    if re.fullmatch(r"[ivxlcdm]{1,8}\.?", s, re.IGNORECASE):
        return True
    return False


def strip_page_numbers(text: str) -> str:
    lines = text.split("\n")
    while lines and _is_page_number(lines[0]):
        lines.pop(0)
    while lines and _is_page_number(lines[-1]):
        lines.pop()
    return "\n".join(lines)


def split_paragraphs(text: str) -> list[str]:
    """Split loose body text into paragraphs on line breaks (chunk-join markers)."""
    return [p.strip() for p in text.split("\n") if p.strip()]


def split_sentences(text: str, max_len: int = 1500) -> list[str]:
    """Sentence-boundary split used when a paragraph overflows a full page."""
    parts = re.split(r"(?<=[.!?…؟])\s+", text.strip())
    chunks: list[str] = []
    buf = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        candidate = f"{buf} {part}".strip() if buf else part
        if buf and len(candidate) > max_len:
            chunks.append(buf)
            buf = part
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return [c for c in chunks if c.strip()] or ([text.strip()] if text.strip() else [])


def _normalize_running_line(s: str) -> str:
    """Normalize a line for repeat matching: drop a leading/trailing bare
    page-number token so numbered running footers ('Animal Farm 2',
    'Animal Farm 3', ...) all map to the same repeat key."""
    s = re.sub(r"\s+\d{1,4}\s*$", "", s).strip()
    s = re.sub(r"^\s*\d{1,4}\s+", "", s).strip()
    s = re.sub(r"\s+[ivxlcdm]{1,8}\.?\s*$", "", s, flags=re.IGNORECASE).strip()
    return s


def strip_running_headers(pages: list[str], max_len: int = 60, min_ratio: float = 0.5) -> list[str]:
    """Drop repeated short header/footer lines so they never glue into body text.

    Conservative by design (a copy of this was once destructive):
      - only SHORT lines (<= max_len chars) are candidates, so a collapsed
        multi-hundred-char body line can never match (the old whole-page bug);
      - a candidate must repeat on >= min_ratio of the non-empty pages
        (counted by normalized form, so 'Animal Farm 2'/'Animal Farm 3'
        footers count together);
      - only the top/bottom lines of each page are removed (header/footer spot);
      - a page is never emptied - if stripping would remove everything, the
        page is kept untouched.
    """
    nonblank = [p for p in pages if p.strip()]
    if not nonblank:
        return pages

    counts: dict[str, int] = {}
    for page in nonblank:
        for line in page.split("\n"):
            s = line.strip()
            if s and len(s) <= max_len:
                key = _normalize_running_line(s)
                if key:
                    counts[key] = counts.get(key, 0) + 1

    threshold = max(2, int(len(nonblank) * min_ratio))
    repeated = {s for s, c in counts.items() if c >= threshold}
    if not repeated:
        return pages

    out = []
    for page in pages:
        lines = page.split("\n")
        while lines and _normalize_running_line(lines[0].strip()) in repeated:
            lines.pop(0)
        while lines and _normalize_running_line(lines[-1].strip()) in repeated:
            lines.pop()
        if lines:
            out.append("\n".join(lines))
        else:
            out.append(page)
    return out


def clean_pages(pages: list[str]) -> list[str]:
    prepared = []
    for p in pages:
        if not p.strip():
            prepared.append("")
            continue
        prepared.append(strip_page_numbers(dehyphenate(p)))
    prepared = strip_running_headers(prepared)
    return [_collapse_wrapped_lines(p) if p.strip() else "" for p in prepared]


def chunk_text(text: str, max_len: int = DEFAULT_BLOCK) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        if len(current) + len(para) + 2 <= max_len:
            current = f"{current}\n\n{para}".strip() if current else para
        else:
            if current.strip():
                chunks.append(current.strip())
            if len(para) > max_len:
                for sub in _split_oversized(para, max_len):
                    if len(current) + len(sub) + 2 <= max_len:
                        current = f"{current}\n\n{sub}".strip() if current else sub
                    else:
                        if current.strip():
                            chunks.append(current.strip())
                        current = sub
            else:
                current = para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_oversized(text: str, max_len: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    parts: list[str] = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 > max_len:
            if current:
                parts.append(current.strip())
            if len(s) > max_len:
                words = s.split()
                current = ""
                for w in words:
                    if len(current) + len(w) + 1 > max_len:
                        parts.append(current.strip())
                        current = w
                    else:
                        current = f"{current} {w}".strip()
            else:
                current = s
        else:
            current = f"{current} {s}".strip()
    if current.strip():
        parts.append(current.strip())
    return parts