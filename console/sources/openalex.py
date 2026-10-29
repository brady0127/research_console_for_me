"""OpenAlex works API (https://docs.openalex.org).

OpenAlex covers journals and conference proceedings, which lets the console
track *published* work in addition to arXiv preprints. Results are filtered
locally by the curated venue table, so predatory or off-topic venues drop out.
"""

from __future__ import annotations

import datetime as dt
import os

from ..common import Http, clean_text

API_URL = "https://api.openalex.org/works"
SELECT = ",".join(
    [
        "id", "doi", "title", "publication_date", "authorships", "primary_location",
        "abstract_inverted_index", "cited_by_count", "type", "ids", "open_access",
    ]
)


def reconstruct_abstract(inverted: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; invert it back to text."""
    if not inverted:
        return ""
    slots: dict[int, str] = {}
    for word, positions in inverted.items():
        for pos in positions:
            slots[pos] = word
    return clean_text(" ".join(slots[i] for i in sorted(slots)))


def _search_expression(keywords: list[str]) -> str:
    return " OR ".join(f'"{k.strip()}"' if " " in k.strip() else k.strip() for k in keywords)


def parse_works(payload: dict) -> list[dict]:
    papers = []
    for work in payload.get("results", []):
        title = clean_text(work.get("title"))
        if not title:
            continue
        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        ids = work.get("ids") or {}
        arxiv_id = None
        doi = (work.get("doi") or "").replace("https://doi.org/", "") or None
        if doi and doi.lower().startswith("10.48550/arxiv."):
            arxiv_id = doi.split("arxiv.", 1)[1]
        papers.append(
            {
                "id": f"openalex:{work['id'].rsplit('/', 1)[-1]}",
                "arxiv_id": arxiv_id,
                "source": "openalex",
                "title": title,
                "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
                "authors": [
                    (a.get("author") or {}).get("display_name", "")
                    for a in work.get("authorships", [])
                ],
                "published": work.get("publication_date") or "",
                "updated": work.get("publication_date") or "",
                "categories": [],
                "primary_category": None,
                "comment": None,
                "journal_ref": None,
                "doi": doi,
                "venue_name": source.get("display_name"),
                "venue_source_type": source.get("type"),
                "cited_by_count": work.get("cited_by_count", 0),
                "url": location.get("landing_page_url") or work.get("doi") or ids.get("openalex"),
                "pdf_url": location.get("pdf_url") or (work.get("open_access") or {}).get("oa_url"),
            }
        )
    return papers


def search(http: Http, track: dict, max_results: int, lookback_days: int,
           mailto: str | None = None, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    since = today - dt.timedelta(days=lookback_days)
    params = {
        "search": _search_expression(track.get("keywords", [])),
        "filter": f"from_publication_date:{since.isoformat()},"
                  f"to_publication_date:{today.isoformat()},has_abstract:true,type:article",
        "sort": "publication_date:desc",
        "per-page": min(max_results, 200),
        "select": SELECT,
    }
    if mailto:
        params["mailto"] = mailto
    api_key = os.environ.get("OPENALEX_API_KEY")
    if api_key:
        params["api_key"] = api_key
    resp = http.get(API_URL, params=params)
    return parse_works(resp.json())
