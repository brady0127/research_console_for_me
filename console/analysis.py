"""Paper analysis and news briefing generation.

Two engines are available:

* `ClaudeEngine` - structured JSON output from the Claude API (used when an
  `ANTHROPIC_API_KEY` is configured).
* `HeuristicEngine` - a transparent, extractive fallback, so the console keeps
  working (with lower-quality reports) without an API key.

The venue tier is never produced by either engine; it comes from
`venues.VenueResolver` so it stays deterministic.
"""

from __future__ import annotations

import json
import os
import re

from .common import LOG, split_sentences, truncate

# --------------------------------------------------------------------------- #
# Schemas for structured output
# --------------------------------------------------------------------------- #
PAPER_SCHEMA = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string", "description": "One sentence, at most 30 words."},
        "summary": {"type": "string", "description": "3-4 sentences: problem, approach, main result."},
        "innovations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 concrete contributions that differ from prior work.",
        },
        "datasets": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Datasets/benchmarks explicitly named in the provided text. Empty if none.",
        },
        "relevance": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "relevance_reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["tldr", "summary", "innovations", "datasets", "relevance", "relevance_reason"],
    "additionalProperties": False,
}

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "A 6-12 word title for this issue."},
        "overview": {"type": "string", "description": "3-4 sentences on the most important developments."},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "item_ids": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["text", "item_ids"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["theme", "points"],
                "additionalProperties": False,
            },
        },
        "top_picks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "overview", "sections", "top_picks"],
    "additionalProperties": False,
}

PAPER_SYSTEM = """You are a careful research analyst writing short reports on new papers for a \
computer and data science PhD student. Be specific and technical; avoid hype and filler.

Rules:
- Base every statement on the provided text only. Never invent results, numbers or datasets.
- "innovations" must name what is new relative to prior work (method, objective, theory, \
system, data), not restate the topic.
- "datasets" lists only datasets or benchmarks explicitly named in the provided text, using \
their canonical names. If none are named, return an empty list.
- "relevance" rates how central the paper is to the research track described by the user \
(5 = core, 1 = only tangential)."""

BRIEFING_SYSTEM = """You are the editor of a concise research-community briefing for a \
computer and data science PhD student. From the supplied news items, write an issue that \
surfaces what actually matters: notable results, new models/datasets/tools, funding and \
policy changes, research-integrity stories and community events.

Rules:
- Use only the supplied items; cite them by id in item_ids. Do not invent facts.
- Group points into 3-6 themes; merge items that cover the same story.
- Skip marketing fluff and items with no research relevance.
- top_picks: the 3-5 item ids most worth reading in full."""


# --------------------------------------------------------------------------- #
# Claude engine
# --------------------------------------------------------------------------- #
class ClaudeEngine:
    name = "claude"

    def __init__(self, model: str, effort: str = "low"):
        import anthropic  # imported lazily so the heuristic path has no hard dependency

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=3)
        self.model = model
        self.effort = effort
        self.use_fallbacks = True

    def _structured(self, system: str, prompt: str, schema: dict, max_tokens: int) -> dict:
        request = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
        )
        if self.use_fallbacks:
            # On a safety-classifier decline, the API retries on a recommended fallback model.
            try:
                response = self.client.beta.messages.create(
                    **request, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
            except self._anthropic.BadRequestError as exc:
                if "fallback" not in str(exc).lower():
                    raise
                LOG.warning("Server-side fallbacks rejected (%s); continuing without them.", exc)
                self.use_fallbacks = False
                response = self.client.messages.create(**request)
        else:
            response = self.client.messages.create(**request)
        if response.stop_reason == "refusal":
            raise RuntimeError("Claude declined the request")
        if response.stop_reason == "max_tokens":
            raise RuntimeError("Claude response hit max_tokens")
        text = next(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    def analyze_paper(self, paper: dict, track: dict, fulltext: str) -> dict:
        parts = [
            f"Research track: {track['name']} - {track.get('description', '')}",
            f"Track keywords: {', '.join(track.get('keywords', []))}",
            "",
            f"Title: {paper['title']}",
            f"Authors: {', '.join(paper['authors'][:12])}",
            f"Venue: {paper['venue']['label']}",
        ]
        if paper.get("comment"):
            parts.append(f"Author comments: {paper['comment']}")
        parts += ["", f"Abstract:\n{paper['abstract']}"]
        if fulltext:
            parts += ["", f"Excerpts from the experimental sections:\n{fulltext}"]
        parts += ["", "Write the report as JSON matching the schema."]
        result = self._structured(PAPER_SYSTEM, "\n".join(parts), PAPER_SCHEMA, 8000)
        result["engine"] = f"claude:{self.model}"
        return result

    def write_briefing(self, items: list[dict], period: str) -> dict:
        lines = [f"Briefing period: {period}", "", "Items (id | source | title | summary):"]
        for item in items:
            lines.append(f"{item['id']} | {item['source_name']} | {item['title']} | "
                         f"{truncate(item['summary'], 320)}")
        result = self._structured(BRIEFING_SYSTEM, "\n".join(lines), BRIEFING_SCHEMA, 16000)
        result["engine"] = f"claude:{self.model}"
        return result


# --------------------------------------------------------------------------- #
# Heuristic engine
# --------------------------------------------------------------------------- #
_CONTRIB_CUES = re.compile(
    r"\b(we (propose|introduce|present|develop|design|show|prove|release|find)|"
    r"our (method|approach|framework|model)|novel|first|outperform|state-of-the-art|"
    r"significantly|improv)\w*",
    re.I,
)
# Common benchmarks in ML / NLP / CV / graph learning / data science.
_KNOWN_DATASETS = [
    "ImageNet", "CIFAR-10", "CIFAR-100", "MNIST", "Fashion-MNIST", "COCO", "MS COCO", "Pascal VOC",
    "ADE20K", "Cityscapes", "Kinetics", "LAION", "CelebA", "SVHN", "Tiny ImageNet", "OpenImages",
    "GLUE", "SuperGLUE", "SQuAD", "MMLU", "MMLU-Pro", "GSM8K", "MATH", "MATH500", "AIME",
    "HumanEval", "MBPP", "BIG-Bench", "BBH", "HellaSwag", "ARC", "TruthfulQA", "Natural Questions",
    "TriviaQA", "HotpotQA", "WikiText", "C4", "The Pile", "MT-Bench", "AlpacaEval", "GPQA",
    "SWE-bench", "LiveCodeBench", "WMT", "XSum", "CNN/DailyMail", "ShareGPT", "Chatbot Arena",
    "OGB", "ogbn-arxiv", "ogbn-products", "Cora", "CiteSeer", "PubMed", "Reddit", "PPI", "ZINC",
    "QM9", "MovieLens", "Amazon Reviews", "Yelp", "Criteo", "UCI", "OpenML", "Kaggle",
    "MIMIC-III", "MIMIC-IV", "UK Biobank", "D4RL", "Atari", "MuJoCo", "nuScenes", "KITTI",
    "Waymo Open", "LibriSpeech", "Common Voice", "AudioSet", "ScanNet", "ShapeNet",
]
_DATASET_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z0-9\-]{1,30}(?:\s[A-Z0-9][A-Za-z0-9\-]{1,20})?)\s(?:dataset|benchmark|corpus)s?\b"
)


class HeuristicEngine:
    name = "heuristic"

    @staticmethod
    def find_datasets(text: str) -> list[str]:
        found: list[str] = []
        for name in _KNOWN_DATASETS:
            if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
                found.append(name)
        for match in _DATASET_PATTERN.finditer(text):
            candidate = match.group(1).strip()
            if candidate.split()[0] not in {"The", "A", "An", "Our", "This", "These", "New", "Large"}:
                found.append(candidate)
        # Drop names that are substrings of longer names already found ("MATH" in "MATH500").
        unique = list(dict.fromkeys(found))
        return [d for d in unique if not any(d != o and d in o for o in unique)][:8]

    def analyze_paper(self, paper: dict, track: dict, fulltext: str) -> dict:
        sentences = split_sentences(paper["abstract"])
        tldr = truncate(sentences[0], 220) if sentences else paper["title"]
        summary = " ".join(sentences[:3])
        innovations = [truncate(s, 260) for s in sentences[1:] if _CONTRIB_CUES.search(s)][:3]
        if not innovations and len(sentences) > 1:
            innovations = [truncate(sentences[1], 260)]
        text = f"{paper['title']} {paper['abstract']} {fulltext}"
        hits = sum(1 for k in track.get("keywords", []) if k.lower() in text.lower())
        return {
            "tldr": tldr,
            "summary": summary,
            "innovations": innovations,
            "datasets": self.find_datasets(text),
            "relevance": max(1, min(5, 1 + hits)),
            "relevance_reason": f"Matches {hits} of the track keywords.",
            "engine": "heuristic",
        }

    def write_briefing(self, items: list[dict], period: str) -> dict:
        by_category: dict[str, list[dict]] = {}
        for item in items:
            by_category.setdefault(item["category"], []).append(item)
        sections = []
        for category, group in by_category.items():
            group = sorted(group, key=lambda x: -x["score"])[:5]
            sections.append(
                {
                    "theme": category,
                    "points": [
                        {"text": f"{it['title']} ({it['source_name']})", "item_ids": [it["id"]]}
                        for it in group
                    ],
                }
            )
        top = sorted(items, key=lambda x: -x["score"])[:5]
        n_sources = len({i["source_id"] for i in items})
        return {
            "headline": f"Research community digest, {period}",
            "overview": f"{len(items)} item{'s' if len(items) != 1 else ''} from "
                        f"{n_sources} source{'s' if n_sources != 1 else ''}, "
                        "grouped by category and ranked by source weight, recency and your "
                        "interest keywords.",
            "sections": sections,
            "top_picks": [it["id"] for it in top],
            "engine": "heuristic",
        }


def make_engine(llm_settings: dict, offline: bool = False):
    """Use Claude when credentials exist, otherwise the heuristic engine."""
    if offline or os.environ.get("CONSOLE_DISABLE_LLM") == "1":
        return HeuristicEngine()
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        LOG.warning("ANTHROPIC_API_KEY not set - falling back to heuristic analysis.")
        return HeuristicEngine()
    try:
        return ClaudeEngine(llm_settings.get("model", "claude-opus-5-5"), llm_settings.get("effort", "low"))
    except Exception as exc:
        LOG.warning("Could not initialise Claude client (%s); using heuristics.", exc)
        return HeuristicEngine()
