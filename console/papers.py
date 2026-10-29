"""Paper tracking pipeline: fetch -> filter -> rank -> analyse -> archive."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from . import fulltext
from .analysis import HeuristicEngine
from .common import (
    DATA_DIR, LOG, STATE_DIR, Http, iso, load_json, normalize, parse_iso, save_json,
    title_key, utcnow,
)
from .sources import arxiv, openalex
from .venues import VenueResolver

TIER_BONUS = {"T1": 4.0, "T2": 2.5, "T3": 1.0, "WS": 0.5, "PP": 0.0, "NR": 0.0}
PAPERS_PATH = DATA_DIR / "papers.json"
SEEN_PATH = STATE_DIR / "seen.json"


@dataclass
class TrackReport:
    track_id: str
    fetched: int = 0
    candidates: int = 0
    selected: int = 0
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Matching and scoring
# --------------------------------------------------------------------------- #
def keyword_hits(keywords: list[str], text: str) -> list[str]:
    """Keywords present in `text`; hyphens = spaces, suffixes allowed (network -> networks)."""
    norm = " " + normalize(text)
    hits = []
    for kw in keywords:
        kw_norm = normalize(kw)
        if kw_norm and re.search(rf"(?<=\s){re.escape(kw_norm)}", norm):
            hits.append(kw)
    return hits


def score_paper(paper: dict, track: dict, now: dt.datetime) -> float:
    title_hits = keyword_hits(track.get("keywords", []), paper["title"])
    abstract_hits = keyword_hits(track.get("keywords", []), paper["abstract"])
    relevance = min(8.0, 3.0 * len(title_hits) + 1.0 * len(abstract_hits))
    tier = TIER_BONUS.get(paper["venue"]["tier"], 0.0)
    published = parse_iso(paper.get("published")) or now
    age_days = max(0.0, (now - published).total_seconds() / 86400)
    recency = 1.5 * max(0.0, 1.0 - age_days / 30.0)
    return round(relevance + tier + recency, 3)


def paper_keys(paper: dict) -> list[str]:
    keys = [f"title:{title_key(paper['title'])}"]
    if paper.get("arxiv_id"):
        keys.append(f"arxiv:{paper['arxiv_id']}")
    if paper.get("doi"):
        keys.append(f"doi:{paper['doi'].lower()}")
    return keys


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
class PaperPipeline:
    def __init__(self, settings: dict, tracks: list[dict], engine, http: Http | None = None,
                 resolver: VenueResolver | None = None, now: dt.datetime | None = None):
        self.settings = settings
        self.cfg = settings.get("papers", {})
        self.llm_cfg = settings.get("llm", {})
        self.tracks = [t for t in tracks if t.get("enabled", True)]
        self.engine = engine
        self.fallback_engine = HeuristicEngine()
        self.http = http or Http(min_interval={"export.arxiv.org": 3.1, "arxiv.org": 1.0,
                                               "api.openalex.org": 0.2})
        self.resolver = resolver or VenueResolver()
        self.now = now or utcnow()

    # ------------------------------------------------------------------ #
    def fetch_track(self, track: dict, report: TrackReport) -> list[dict]:
        papers: list[dict] = []
        sources = track.get("sources", ["arxiv", "openalex"])
        if "arxiv" in sources:
            try:
                papers += arxiv.search(self.http, track, self.cfg.get("arxiv_max_results_per_track", 120))
            except Exception as exc:
                report.errors.append(f"arXiv: {exc}")
                LOG.error("[%s] arXiv fetch failed: %s", track["id"], exc)
        if "openalex" in sources:
            try:
                papers += openalex.search(
                    self.http, track,
                    self.cfg.get("openalex_max_results_per_track", 80),
                    max(track.get("lookback_days", 3), self.cfg.get("openalex_lookback_days", 21)),
                    mailto=self.settings.get("contact_email") or None,
                    today=self.now.date(),
                )
            except Exception as exc:
                report.errors.append(f"OpenAlex: {exc}")
                LOG.error("[%s] OpenAlex fetch failed: %s", track["id"], exc)
        report.fetched = len(papers)
        return papers

    def attach_venue(self, paper: dict) -> None:
        if paper["source"] == "arxiv":
            info = self.resolver.from_arxiv(paper.get("comment"), paper.get("journal_ref"))
        else:
            info = self.resolver.from_source_name(paper.get("venue_name"), paper.get("venue_source_type"))
        paper["venue"] = info.to_dict()

    def filter_candidates(self, track: dict, papers: list[dict], seen: dict) -> list[dict]:
        lookback = dt.timedelta(days=track.get("lookback_days", 3))
        oa_lookback = dt.timedelta(days=max(track.get("lookback_days", 3),
                                            self.cfg.get("openalex_lookback_days", 21)))
        out, local_keys = [], set()
        for paper in papers:
            text = f"{paper['title']} {paper['abstract']}"
            published = parse_iso(paper.get("published"))
            window = lookback if paper["source"] == "arxiv" else oa_lookback
            if published is None or self.now - published > window + dt.timedelta(hours=12):
                continue
            if not keyword_hits(track.get("keywords", []), text):
                continue  # precision guard: API search is fuzzier than our keyword list
            if keyword_hits(track.get("exclude", []), text):
                continue
            self.attach_venue(paper)
            if not VenueResolver.passes(paper["venue"]["tier"], track.get("min_tier", "T2"),
                                        track.get("include_preprints", True),
                                        on_arxiv=paper["source"] == "arxiv"):
                continue
            keys = paper_keys(paper)
            if any(k in seen for k in keys) or any(k in local_keys for k in keys):
                continue
            local_keys.update(keys)
            paper["matched_keywords"] = keyword_hits(track.get("keywords", []), text)
            paper["score"] = score_paper(paper, track, self.now)
            out.append(paper)
        out.sort(key=lambda p: -p["score"])
        return out

    def analyze(self, paper: dict, track: dict) -> None:
        text = ""
        if self.llm_cfg.get("fulltext_for_datasets", True) and paper.get("arxiv_id"):
            text = fulltext.fetch_experimental_text(
                self.http, paper["arxiv_id"], self.llm_cfg.get("fulltext_char_budget", 9000))
        try:
            analysis = self.engine.analyze_paper(paper, track, text)
        except Exception as exc:
            LOG.warning("Analysis failed for %s (%s); using heuristics.", paper["id"], exc)
            analysis = self.fallback_engine.analyze_paper(paper, track, text)
            analysis["note"] = "LLM analysis failed for this paper; heuristic summary shown."
        analysis["datasets_source"] = "full text" if text else "abstract"
        paper["analysis"] = analysis

    # ------------------------------------------------------------------ #
    def run(self) -> dict:
        seen: dict = load_json(SEEN_PATH, {})
        archive = load_json(PAPERS_PATH, {"papers": []})
        run_id = self.now.strftime("%Y%m%dT%H%MZ")
        selected: dict[str, dict] = {}   # title-key -> paper (dedup across tracks)
        reports = []

        for track in self.tracks:
            report = TrackReport(track["id"])
            raw = self.fetch_track(track, report)
            candidates = self.filter_candidates(track, raw, seen)
            report.candidates = len(candidates)
            chosen = 0
            for paper in candidates:
                if chosen >= track.get("max_papers", 8):
                    break
                key = title_key(paper["title"])
                if key in selected:  # already picked (and analysed) by another track
                    if track["id"] not in selected[key]["tracks"]:
                        selected[key]["tracks"].append(track["id"])
                    continue
                paper.update(tracks=[track["id"]], fetched_at=iso(self.now), run_id=run_id)
                self.analyze(paper, track)
                selected[key] = paper
                chosen += 1
            report.selected = chosen
            reports.append(report)
            LOG.info("[%s] fetched=%d candidates=%d selected=%d", track["id"],
                     report.fetched, report.candidates, report.selected)

        new_papers = sorted(selected.values(), key=lambda p: -p["score"])
        for paper in new_papers:
            paper.pop("venue_source_type", None)
            for key in paper_keys(paper):
                seen[key] = iso(self.now)

        # Archive: newest first, capped.
        papers = new_papers + archive.get("papers", [])
        papers.sort(key=lambda p: (p.get("fetched_at", ""), p.get("score", 0)), reverse=True)
        papers = papers[: self.cfg.get("archive_cap", 1500)]
        save_json(PAPERS_PATH, {"generated_at": iso(self.now), "papers": papers}, compact=True)

        retention = dt.timedelta(days=self.cfg.get("seen_retention_days", 365))
        seen = {k: v for k, v in seen.items() if self.now - (parse_iso(v) or self.now) <= retention}
        save_json(SEEN_PATH, seen, compact=True)

        return {
            "run_id": run_id,
            "time": iso(self.now),
            "new_papers": new_papers,
            "tracks": [r.__dict__ for r in reports],
            "engine": getattr(self.engine, "name", "unknown"),
        }

