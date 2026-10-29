"""arXiv API client (https://info.arxiv.org/help/api/user-manual.html).

The API asks clients to wait ~3 s between calls; `Http` enforces that pacing.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ..common import Http, clean_text

API_URL = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}


def _term(keyword: str) -> str:
    """One keyword -> a title-or-abstract clause; multi-word keywords become phrases."""
    kw = keyword.strip().replace('"', "")
    token = f'"{kw}"' if re.search(r"[\s-]", kw) else kw
    return f"ti:{token} OR abs:{token}"


def build_query(keywords: list[str], categories: list[str], exclude: list[str]) -> str:
    parts = []
    if keywords:
        parts.append("(" + " OR ".join(f"({_term(k)})" for k in keywords) + ")")
    if categories:
        parts.append("(" + " OR ".join(f"cat:{c}" for c in categories) + ")")
    query = " AND ".join(parts) if parts else "all:*"
    for ex in exclude:
        query += f" ANDNOT ({_term(ex)})"
    return query


def parse_feed(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    papers = []
    for entry in root.findall("atom:entry", NS):
        raw_id = entry.findtext("atom:id", default="", namespaces=NS)
        match = re.search(r"arxiv\.org/abs/([^\s]+?)(v\d+)?$", raw_id)
        if not match:
            continue  # error entries carry no arXiv id
        arxiv_id = match.group(1)
        links = {
            (link.get("title") or link.get("rel")): link.get("href")
            for link in entry.findall("atom:link", NS)
        }
        primary = entry.find("arxiv:primary_category", NS)
        papers.append(
            {
                "id": f"arxiv:{arxiv_id}",
                "arxiv_id": arxiv_id,
                "source": "arxiv",
                "title": clean_text(entry.findtext("atom:title", default="", namespaces=NS)),
                "abstract": clean_text(entry.findtext("atom:summary", default="", namespaces=NS)),
                "authors": [
                    clean_text(a.findtext("atom:name", default="", namespaces=NS))
                    for a in entry.findall("atom:author", NS)
                ],
                "published": entry.findtext("atom:published", default="", namespaces=NS),
                "updated": entry.findtext("atom:updated", default="", namespaces=NS),
                "categories": [c.get("term") for c in entry.findall("atom:category", NS)],
                "primary_category": primary.get("term") if primary is not None else None,
                "comment": clean_text(entry.findtext("arxiv:comment", default="", namespaces=NS)) or None,
                "journal_ref": clean_text(entry.findtext("arxiv:journal_ref", default="", namespaces=NS)) or None,
                "doi": entry.findtext("arxiv:doi", default=None, namespaces=NS),
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": links.get("pdf") or f"https://arxiv.org/pdf/{arxiv_id}",
            }
        )
    return papers


def search(http: Http, track: dict, max_results: int) -> list[dict]:
    query = build_query(track.get("keywords", []), track.get("arxiv_categories", []),
                        track.get("exclude", []))
    resp = http.get(
        API_URL,
        params={
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        },
    )
    return parse_feed(resp.text)
