"""Offline tests: every network call is served from tests/fixtures."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from console import feeds, fulltext, news, papers
from console.analysis import HeuristicEngine
from console.common import load_config
from console.sources import arxiv, openalex
from console.venues import VenueResolver

FIXTURES = Path(__file__).parent / "fixtures"
NOW = dt.datetime(2026, 10, 29, 8, 0, tzinfo=dt.timezone.utc)


class FakeResponse:
    def __init__(self, body: bytes):
        self.content = body
        self.text = body.decode("utf-8")

    def json(self):
        return json.loads(self.text)


class FakeHttp:
    """Routes URLs to fixture files and records every request."""

    def __init__(self):
        self.calls: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, **_):
        self.calls.append((url, params))
        if "export.arxiv.org" in url:
            name = "arxiv_feed.xml"
        elif "api.openalex.org" in url:
            name = "openalex_works.json"
        elif "arxiv.org/html/" in url:
            name = "arxiv_html.html"
        elif "news" in url or url.endswith(".xml") or "feed" in url:
            name = "news_feed.xml"
        else:
            raise RuntimeError(f"unexpected URL {url}")
        return FakeResponse((FIXTURES / name).read_bytes())


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(papers, "PAPERS_PATH", tmp_path / "data" / "papers.json")
    monkeypatch.setattr(papers, "SEEN_PATH", tmp_path / "state" / "seen.json")
    monkeypatch.setattr(news, "NEWS_DIR", tmp_path / "data" / "news")
    monkeypatch.setattr(news, "INDEX_PATH", tmp_path / "data" / "news" / "index.json")
    monkeypatch.setattr(news, "SEEN_PATH", tmp_path / "state" / "news_seen.json")
    monkeypatch.setattr(feeds, "FEED_DIR", tmp_path / "feeds")
    return tmp_path


TRACK = {
    "id": "reasoning", "name": "LLM Reasoning", "description": "", "enabled": True,
    "keywords": ["chain-of-thought", "mathematical reasoning", "self-consistency", "process reward model"],
    "exclude": [], "arxiv_categories": ["cs.CL"], "sources": ["arxiv", "openalex"],
    "include_preprints": True, "min_tier": "T2", "lookback_days": 3, "max_papers": 10,
}


# --------------------------------------------------------------------------- #
# Venue resolution
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def resolver():
    return VenueResolver()


@pytest.mark.parametrize(
    "comment, journal_ref, tier, status, label",
    [
        ("Accepted at NeurIPS 2026 (Spotlight)", None, "T1", "accepted", "NeurIPS 2026 (Spotlight)"),
        ("ICLR 2026", None, "T1", "accepted", "ICLR 2026"),
        ("Under review at ICLR 2027", None, "PP", "preprint", "arXiv preprint"),
        ("Submitted to ICML 2026; 12 pages", None, "PP", "preprint", "arXiv preprint"),
        ("Accepted to the ICML 2026 Workshop on Reasoning", None, "WS", "workshop", "ICML 2026 Workshop"),
        ("Findings of EMNLP 2025", None, "T2", "accepted", "Findings of EMNLP 2025"),
        ("Accepted to NAACL 2025 main conference", None, "T2", "accepted", "NAACL 2025"),
        ("12 pages, 4 figures", None, "PP", "preprint", "arXiv preprint"),
        ("Published in Nature Communications", None, "T2", "accepted", "Nature Communications"),
        ("Accepted for publication in Nature", None, "T1", "accepted", "Nature"),
        ("The nature of the problem is discussed", None, "PP", "preprint", "arXiv preprint"),
        (None, "Nature 620, 47-53 (2023)", "T1", "published", "Nature 2023"),
        (None, "Proceedings of the 40th International Conference on Machine Learning, PMLR 202, 2023",
         "T1", "published", "ICML 2023"),
        ("Accepted at KDD 2026", None, "T1", "accepted", "KDD 2026"),
        ("Accepted at PAKDD 2026", None, "T3", "accepted", "PAKDD 2026"),
        ("Accepted to SIGMOD 2027", None, "T1", "accepted", "SIGMOD 2027"),
        ("PVLDB 2026", None, "T1", "accepted", "VLDB 2026"),
        ("Accepted at SoCG 2026", None, "T2", "accepted", "SoCG 2026"),
        ("Accepted by DASFAA 2026", None, "T2", "accepted", "DASFAA 2026"),
        ("Accepted at SISAP 2026", None, "T3", "accepted", "SISAP 2026"),
    ],
)
def test_arxiv_venue(resolver, comment, journal_ref, tier, status, label):
    info = resolver.from_arxiv(comment, journal_ref)
    assert (info.tier, info.status, info.label) == (tier, status, label)


@pytest.mark.parametrize(
    "name, tier, key",
    [
        ("IEEE Transactions on Pattern Analysis and Machine Intelligence", "T1", "TPAMI"),
        ("Nature", "T1", "Nature"),
        ("Nature Reviews Physics", "NR", None),
        ("2026 International Conference on Machine Learning and Applications (ICMLA)", "NR", None),
        ("Proceedings of the AAAI Conference on Artificial Intelligence", "T1", "AAAI"),
        ("arXiv (Cornell University)", "PP", None),
        ("Proceedings of the National Academy of Sciences of the United States of America", "T1", "PNAS"),
        ("Information Processing & Management", "T2", "IP&M"),
    ],
)
def test_source_venue(resolver, name, tier, key):
    info = resolver.from_source_name(name)
    assert (info.tier, info.key) == (tier, key)


def test_tier_filter():
    passes = VenueResolver.passes
    assert passes("T1", "T2", include_preprints=False)
    assert not passes("T3", "T2", include_preprints=True)               # published, below bar
    assert passes("T3", "T2", include_preprints=True, on_arxiv=True)   # still a preprint
    assert not passes("PP", "T2", include_preprints=False, on_arxiv=True)
    assert not passes("NR", "T3", include_preprints=True)
    assert passes("NR", "any", include_preprints=False)


def test_venue_table_is_consistent():
    table = load_config("venues.json")
    keys = [v["key"] for v in table["venues"]]
    assert len(keys) == len(set(keys))
    assert all(v["tier"] in {"T1", "T2", "T3"} for v in table["venues"])


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #
def test_arxiv_query_and_parse():
    query = arxiv.build_query(["chain-of-thought", "reasoning"], ["cs.CL", "cs.LG"], ["survey"])
    assert query == ('((ti:"chain-of-thought" OR abs:"chain-of-thought") OR (ti:reasoning OR abs:reasoning))'
                     " AND (cat:cs.CL OR cat:cs.LG) ANDNOT (ti:survey OR abs:survey)")
    parsed = arxiv.parse_feed((FIXTURES / "arxiv_feed.xml").read_text())
    assert len(parsed) == 5
    first = parsed[0]
    assert first["arxiv_id"] == "2610.11111"
    assert first["title"].startswith("Scaling Test-Time Compute with Process")
    assert first["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert first["comment"].startswith("Accepted at NeurIPS 2026")
    assert first["pdf_url"] == "http://arxiv.org/pdf/2610.11111v1"


def test_openalex_parse():
    parsed = openalex.parse_works(json.loads((FIXTURES / "openalex_works.json").read_text()))
    assert parsed[0]["abstract"] == "We study mathematical reasoning with verifiers."
    assert parsed[0]["doi"] == "10.1109/tpami.2026.0001"
    assert parsed[0]["venue_name"].startswith("IEEE Transactions")


def test_fulltext_extraction():
    text = fulltext.extract_sections((FIXTURES / "arxiv_html.html").read_text(), 5000)
    assert "GSM8K" in text and "Table 1" in text
    assert "Intro text" not in text and "var x" not in text and "91.2" not in text


# --------------------------------------------------------------------------- #
# Heuristic analysis
# --------------------------------------------------------------------------- #
def test_heuristic_datasets():
    found = HeuristicEngine.find_datasets("We evaluate on GSM8K and MATH500, plus the FooBar benchmark.")
    assert found == ["GSM8K", "MATH500", "FooBar"]


def test_keyword_hits():
    assert papers.keyword_hits(["graph neural network"], "Graph Neural Networks for X") == ["graph neural network"]
    assert papers.keyword_hits(["chain-of-thought"], "chain of thought prompting") == ["chain-of-thought"]
    assert papers.keyword_hits(["math"], "aftermath of the storm") == []


# --------------------------------------------------------------------------- #
# End-to-end pipelines
# --------------------------------------------------------------------------- #
SETTINGS = {
    "site_url": "https://example.github.io/console/",
    "llm": {"fulltext_for_datasets": True, "fulltext_char_budget": 4000},
    "papers": {"openalex_lookback_days": 21, "archive_cap": 100},
    "news": {"cadence_days": 3, "max_items_per_source": 10, "interest_keywords": ["LLM", "funding"]},
}


def test_paper_pipeline_end_to_end(sandbox):
    http = FakeHttp()
    result = papers.PaperPipeline(SETTINGS, [TRACK], HeuristicEngine(), http=http, now=NOW).run()
    titles = [p["title"] for p in result["new_papers"]]

    # Kept: in-window, on-topic arXiv papers (incl. under-review / workshop preprints) and TPAMI.
    assert "Mathematical Reasoning with Verifier-Guided Search" in titles
    assert any(t.startswith("Scaling Test-Time Compute") for t in titles)
    assert "Chain-of-Thought Faithfulness under Distribution Shift" in titles
    assert "Self-Consistency for Small Models" in titles
    # Dropped: off-topic, too old, unranked venue, ICMLA mistaken for ICML.
    assert "A Study of Protein Folding Kinetics" not in titles
    assert "An Old Chain-of-Thought Paper" not in titles
    assert "Mathematical Reasoning in a Predatory Venue" not in titles
    assert "Mathematical Reasoning at ICMLA" not in titles

    # Highest score: the NeurIPS spotlight with the most keyword matches.
    top = result["new_papers"][0]
    assert top["venue"]["label"] == "NeurIPS 2026 (Spotlight)"
    assert top["analysis"]["datasets_source"] == "full text"
    assert "GSM8K" in top["analysis"]["datasets"]

    # A second run on the same data finds nothing new (dedup via state/seen.json).
    again = papers.PaperPipeline(SETTINGS, [TRACK], HeuristicEngine(), http=FakeHttp(), now=NOW).run()
    assert again["new_papers"] == []
    archive = json.loads(papers.PAPERS_PATH.read_text())
    assert len(archive["papers"]) == len(titles)

    feeds.write_papers_feed(archive["papers"], SETTINGS["site_url"])
    assert "<entry>" in (feeds.FEED_DIR / "papers.xml").read_text()


def test_paper_dedup_across_tracks(sandbox):
    second = dict(TRACK, id="reasoning-2", name="Reasoning 2")
    result = papers.PaperPipeline(SETTINGS, [TRACK, second], HeuristicEngine(),
                                  http=FakeHttp(), now=NOW).run()
    assert all(sorted(p["tracks"]) == ["reasoning", "reasoning-2"] for p in result["new_papers"])


def test_news_pipeline_and_cadence(sandbox):
    sources = {"sources": [{"id": "ex", "name": "Example", "category": "Science News",
                            "url": "https://example.org/news.xml", "weight": 1.0}]}
    issue = news.NewsPipeline(SETTINGS, sources, HeuristicEngine(), http=FakeHttp(), now=NOW).run()
    assert issue["id"] == "2026-10-29"
    assert [i["title"] for i in issue["items"]] == [
        "New large language model benchmark exposes reasoning gaps",
        "NSF announces new AI institutes funding",
    ]
    assert issue["items"][0]["summary"] == "Researchers release a dataset to test LLM reasoning."

    # Not due one day later; due three days later (minus cron tolerance).
    later = news.NewsPipeline(SETTINGS, sources, HeuristicEngine(), http=FakeHttp(),
                              now=NOW + dt.timedelta(days=1))
    assert later.run() is None
    due, _ = news.is_due(SETTINGS, NOW + dt.timedelta(days=3, hours=-2))
    assert due
    forced = news.NewsPipeline(SETTINGS, sources, HeuristicEngine(), http=FakeHttp(),
                               now=NOW + dt.timedelta(days=1)).run(force=True)
    assert forced == {"skipped": True, "sources": forced["sources"]}  # everything already seen


# --------------------------------------------------------------------------- #
# Claude engine request/response shape (against a local mock of the API)
# --------------------------------------------------------------------------- #
def test_claude_engine_request_shape(monkeypatch):
    import http.server
    import threading

    from console.analysis import PAPER_SCHEMA, ClaudeEngine

    captured = {}
    canned = {
        "tldr": "A PRM allocates test-time compute.", "summary": "S.",
        "innovations": ["Step-level reward model."], "datasets": ["GSM8K"],
        "relevance": 5, "relevance_reason": "Core topic.",
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["content-length"])
            captured["path"] = self.path
            captured["beta"] = self.headers.get("anthropic-beta")
            captured["body"] = json.loads(self.rfile.read(length))
            body = json.dumps({
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [{"type": "thinking", "thinking": "", "signature": "x"},
                            {"type": "text", "text": json.dumps(canned)}],
                "stop_reason": "end_turn", "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    try:
        engine = ClaudeEngine("claude-opus-5-5", "low")
        paper = {"title": "T", "authors": ["A"], "abstract": "Abs.", "comment": None,
                 "venue": {"label": "arXiv preprint"}}
        result = engine.analyze_paper(paper, TRACK, "Experiments text")
    finally:
        server.shutdown()

    assert captured["path"].startswith("/v1/messages")
    assert "server-side-fallback-2026-07-01" in captured["beta"]
    body = captured["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["fallbacks"] == "default"
    assert body["output_config"] == {"effort": "low",
                                     "format": {"type": "json_schema", "schema": PAPER_SCHEMA}}
    assert "Experiments text" in body["messages"][0]["content"]
    assert result["datasets"] == ["GSM8K"] and result["engine"] == "claude:claude-opus-5-5"


# --------------------------------------------------------------------------- #
# Shipped configuration
# --------------------------------------------------------------------------- #
def test_tracks_config_is_valid():
    """Guards edits made by hand or from the web UI."""
    import re

    tracks = load_config("tracks.json")["tracks"]
    ids = [t["id"] for t in tracks]
    assert len(ids) == len(set(ids))
    for t in tracks:
        assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", t["id"]), t["id"]
        assert t["name"] and t["keywords"] and all(isinstance(k, str) and k.strip() for k in t["keywords"])
        assert t["min_tier"] in {"T1", "T2", "T3", "any"}
        assert set(t["sources"]) <= {"arxiv", "openalex"} and t["sources"]
        assert 1 <= t["lookback_days"] <= 30 and 1 <= t["max_papers"] <= 50
        assert all(re.fullmatch(r"[a-z-]+(\.[A-Za-z-]+)?", c) for c in t["arxiv_categories"])


ANNS = {t["id"]: t for t in load_config("tracks.json")["tracks"]}


@pytest.mark.parametrize(
    "track_id, title, expected",
    [
        ("anns-core", "Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical "
                      "Navigable Small World Graphs", True),
        ("anns-core", "DiskANN: Fast Accurate Billion-point Nearest Neighbor Search on a Single Node", True),
        ("anns-core", "SPANN: Highly-efficient Billion-scale Approximate Nearest Neighborhood Search", True),
        ("anns-core", "Product Quantization for Nearest Neighbor Search", True),
        ("anns-core", "RaBitQ: Quantizing High-Dimensional Vectors with a Theoretical Error Bound for "
                      "Approximate Nearest Neighbor Search", True),
        ("anns-core", "Graph-Based Indexes for Filtered Queries", True),
        ("anns-core", "k-Nearest Neighbor Classifiers for Tabular Data", False),
        ("anns-core", "Annual Review of Graph Neural Networks", False),
        ("anns-core", "Vector-Quantized Diffusion Models for Image Synthesis", False),
        ("vector-search-systems", "Milvus: A Purpose-Built Vector Data Management System", True),
        ("vector-search-systems", "Filtered Vector Search with Range Predicates on GPUs", True),
        ("vector-search-systems", "Embedding-Based Retrieval in Facebook Search", True),
        ("vector-search-systems", "Support Vector Machines for Text Classification", False),
    ],
)
def test_anns_keyword_precision(track_id, title, expected):
    assert bool(papers.keyword_hits(ANNS[track_id]["keywords"], title)) is expected


def test_anns_arxiv_query_is_well_formed():
    t = ANNS["anns-core"]
    query = arxiv.build_query(t["keywords"], t["arxiv_categories"], t["exclude"])
    assert query.count("(") == query.count(")")
    assert '(ti:"approximate nearest neighbor" OR abs:"approximate nearest neighbor")' in query
    assert "(ti:HNSW OR abs:HNSW)" in query and "cat:cs.CG" in query
    assert len(query) < 2000  # stays well inside URL limits
