"""Venue recognition and tier assignment.

A paper's venue tier is computed deterministically from a curated table
(`config/venues.json`) rather than asked of the LLM, so the label is
reproducible and auditable. Three kinds of evidence are used:

1. A published venue name (OpenAlex `primary_location.source`).
2. An arXiv `journal_ref` field (always means "published").
3. Free-text arXiv comments ("Accepted at NeurIPS 2025", "ICLR 2026 (oral)").
   Comments that say "under review" / "submitted to" are deliberately ignored,
   and workshop / companion / extended-abstract papers get their own tier.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .common import load_config, normalize

TIER_ORDER = {"T1": 3, "T2": 2, "T3": 1, "WS": 0, "NR": 0, "PP": 0}

_REVIEW_CUES = re.compile(
    r"\b(under review|under submission|in submission|submitted to|submitted for|"
    r"submission to|rejected|in review|preprint version|work in progress)\b",
    re.I,
)
_ACCEPT_CUES = re.compile(
    r"\b(accepted|accept|to appear|appears? in|appearing in|published|camera[- ]ready|"
    r"proceedings|oral|spotlight|poster|main (conference|track)|presented at)\b",
    re.I,
)
_WORKSHOP_CUES = re.compile(
    r"\b(workshops?|extended abstracts?|companion|doctoral consortium|demo track|"
    r"student research workshop|tiny papers?|blogpost track)\b",
    re.I,
)
_FINDINGS_CUE = re.compile(r"\bfindings\b", re.I)
_YEAR = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)|'\d{2}\b")


@dataclass
class VenueInfo:
    label: str                 # display text, e.g. "NeurIPS 2025 (Spotlight)"
    key: str | None            # canonical key in the venue table, if recognised
    tier: str                  # T1 | T2 | T3 | WS | PP | NR
    status: str                # published | accepted | workshop | preprint
    venue_type: str | None = None
    ccf: str | None = None
    core: str | None = None
    evidence: str = ""         # the text the decision was based on
    confidence: str = "high"   # high | inferred
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class VenueResolver:
    def __init__(self, table: dict | None = None):
        table = table or load_config("venues.json")
        self.tiers = table["tiers"]
        self.venues = {v["key"]: v for v in table["venues"]}
        # Phrase aliases sorted longest-first so specific names win
        # (e.g. "pacific asia conference on knowledge discovery..." before "knowledge discovery...").
        self._aliases: list[tuple[str, dict]] = sorted(
            ((normalize(a), v) for v in table["venues"] for a in v.get("aliases", [])),
            key=lambda item: -len(item[0]),
        )
        self._exact: dict[str, dict] = {
            normalize(name): v for v in table["venues"] for name in v.get("exact", [])
        }
        self._exact_patterns = [
            (
                re.compile(
                    r"(?i:published|accepted|appears?|appearing|to appear)(?:\s+(?i:for publication))?"
                    r"\s+(?i:in|at|by|for)\s+"
                    r"(?:(?i:the)\s+)?" + re.escape(name) + r"(?![\w-])(?!\s+[A-Z&])"
                ),
                v,
            )
            for v in table["venues"]
            for name in v.get("exact", [])
        ]

    # ------------------------------------------------------------------ #
    def _match_alias(self, text: str) -> dict | None:
        norm = f" {normalize(text)} "
        for alias, venue in self._aliases:
            needle = f" {alias} "
            idx = norm.find(needle)
            while idx != -1:
                tail = norm[idx + len(needle):]
                # "International Conference on Machine Learning and Applications" is not ICML.
                if not (len(alias.split()) >= 3 and tail.startswith("and ")):
                    return venue
                idx = norm.find(needle, idx + 1)
        return None

    def _match_exact_name(self, name: str) -> dict | None:
        return self._exact.get(normalize(name))

    def _info(self, venue: dict, label: str, status: str, evidence: str,
              confidence: str = "high", tier: str | None = None) -> VenueInfo:
        return VenueInfo(
            label=label,
            key=venue["key"],
            tier=tier or venue["tier"],
            status=status,
            venue_type=venue["type"],
            ccf=venue.get("ccf"),
            core=venue.get("core"),
            evidence=evidence,
            confidence=confidence,
            note=venue.get("note"),
        )

    @staticmethod
    def _label(venue: dict, text: str) -> str:
        year = _YEAR.search(text)
        label = venue["key"]
        if year:
            y = year.group(0)
            label += " " + ("20" + y[1:] if y.startswith("'") else y)
        for tag in ("Oral", "Spotlight", "Best Paper", "Highlight"):
            if re.search(rf"\b{tag}\b", text, re.I):
                label += f" ({tag})"
                break
        return label

    # ------------------------------------------------------------------ #
    def from_source_name(self, source_name: str | None, source_type: str | None = None) -> VenueInfo:
        """Resolve a published venue name, e.g. an OpenAlex source display name."""
        if not source_name:
            return VenueInfo(label="Unknown venue", key=None, tier="NR", status="published")
        if source_type == "repository" or re.search(r"\barxiv\b|biorxiv|medrxiv|ssrn|research square",
                                                     source_name, re.I):
            return VenueInfo(label=source_name, key=None, tier="PP", status="preprint",
                             evidence=source_name)
        venue = self._match_exact_name(source_name) or self._match_alias(source_name)
        if venue is None:
            return VenueInfo(label=source_name, key=None, tier="NR", status="published",
                             evidence=source_name)
        if _WORKSHOP_CUES.search(source_name):
            return self._info(venue, f"{venue['key']} Workshop", "workshop", source_name, tier="WS")
        return self._info(venue, self._label(venue, source_name), "published", source_name)

    def from_arxiv(self, comment: str | None, journal_ref: str | None) -> VenueInfo:
        """Infer the venue of an arXiv paper from `journal_ref` and comments."""
        if journal_ref:
            info = self._from_journal_ref(journal_ref)
            if info is not None:
                return info
        if comment:
            info = self._from_comment(comment)
            if info is not None:
                return info
        if journal_ref:
            return VenueInfo(label=journal_ref, key=None, tier="NR", status="published",
                             evidence=journal_ref)
        return VenueInfo(label="arXiv preprint", key=None, tier="PP", status="preprint")

    def _from_journal_ref(self, ref: str) -> VenueInfo | None:
        for name_norm, venue in self._exact.items():
            # Journal references look like "Nature 620, 47-53 (2023)".
            if re.match(rf"^{re.escape(name_norm)}( \d|$)", normalize(ref)):
                return self._info(venue, self._label(venue, ref), "published", ref)
        venue = self._match_alias(ref)
        if venue is None:
            return None
        if _WORKSHOP_CUES.search(ref):
            return self._info(venue, f"{venue['key']} Workshop", "workshop", ref, tier="WS")
        return self._info(venue, self._label(venue, ref), "published", ref)

    def _from_comment(self, comment: str) -> VenueInfo | None:
        clauses = [c.strip() for c in re.split(r"[;\n|]|(?<=[a-z0-9)])\.\s", comment) if c.strip()]
        for clause in clauses:
            if _REVIEW_CUES.search(clause):
                continue
            for pattern, venue in self._exact_patterns:
                if pattern.search(clause):
                    return self._info(venue, self._label(venue, clause), "accepted", clause)
            venue = self._match_alias(clause)
            if venue is None:
                continue
            if _WORKSHOP_CUES.search(clause):
                return self._info(venue, self._label(venue, clause).split(" (")[0] + " Workshop",
                                  "workshop", clause, tier="WS")
            explicit = bool(_ACCEPT_CUES.search(clause))
            if not explicit and not _YEAR.search(clause):
                # A bare mention without a year or acceptance cue is too weak.
                continue
            if _FINDINGS_CUE.search(clause):
                label = f"Findings of {venue['key']}"
                year = _YEAR.search(clause)
                if year:
                    label += " " + year.group(0)
                info = self._info(venue, label, "accepted", clause,
                                  "high" if explicit else "inferred",
                                  tier="T2" if venue["tier"] == "T1" else "T3")
                info.note = "Findings track (companion volume to the main conference)."
                return info
            return self._info(venue, self._label(venue, clause), "accepted", clause,
                              "high" if explicit else "inferred")
        return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def passes(tier: str, min_tier: str, include_preprints: bool, on_arxiv: bool = False) -> bool:
        """Apply a track's quality filter.

        `min_tier` gates published/accepted venues. An arXiv paper is a preprint
        whatever its venue, so with `include_preprints` it always passes; this keeps
        "accepted at a C-ranked venue" from scoring below "no venue at all".
        """
        meets_tier = min_tier == "any" or (
            tier not in ("NR", "PP", "WS") and TIER_ORDER[tier] >= TIER_ORDER.get(min_tier, 0)
        )
        if on_arxiv or tier in ("PP", "WS"):
            return include_preprints or meets_tier
        return meets_tier
