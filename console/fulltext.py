"""Experimental-section extraction from arXiv's HTML rendering.

Abstracts frequently omit the datasets a paper evaluates on. arXiv serves an
HTML version (https://arxiv.org/html/<id>) for most recent submissions; we pull
the sections most likely to name datasets so the analysis is grounded in the
paper rather than guessed.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .common import LOG, Http, clean_text

HTML_URL = "https://arxiv.org/html/{arxiv_id}"
SECTION_HINT = re.compile(
    r"experiment|evaluation|dataset|data\b|benchmark|setup|empirical|results", re.I
)


def extract_sections(html_text: str, char_budget: int) -> str:
    soup = BeautifulSoup(html_text, "html.parser")
    for tag in soup(["script", "style", "math", "nav", "footer"]):
        tag.decompose()
    # Keep only captions of figures/tables: they often name datasets, the cells are noise.
    for fig in soup.find_all("figure"):
        caption = fig.find("figcaption")
        fig.replace_with(f" {clean_text(caption.get_text(' '))} " if caption else " ")
    chunks: list[str] = []
    used = 0
    for section in soup.select("section.ltx_section, section.ltx_appendix"):
        heading = section.find(re.compile(r"^h[1-6]$"))
        title = clean_text(heading.get_text(" ")) if heading else ""
        if not SECTION_HINT.search(title):
            continue
        text = clean_text(section.get_text(" "))
        remaining = char_budget - used
        if remaining <= 200:
            break
        chunk = f"[{title}] {text[:remaining]}"
        chunks.append(chunk)
        used += len(chunk)
    return "\n\n".join(chunks)


def fetch_experimental_text(http: Http, arxiv_id: str | None, char_budget: int) -> str:
    """Return experiment-related text, or '' when unavailable (never raises)."""
    if not arxiv_id:
        return ""
    try:
        resp = http.get(HTML_URL.format(arxiv_id=arxiv_id))
    except Exception as exc:  # HTML is missing for some papers; that's fine.
        LOG.info("No HTML full text for %s (%s)", arxiv_id, exc)
        return ""
    return extract_sections(resp.text, char_budget)
