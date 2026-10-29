"""Shared utilities: paths, JSON I/O, HTTP session, text helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

LOG = logging.getLogger("console")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
SITE_DIR = ROOT / "site"
DATA_DIR = SITE_DIR / "data"
FEED_DIR = SITE_DIR / "feeds"
STATE_DIR = ROOT / "state"

USER_AGENT = "ResearchConsole/1.0 (personal research dashboard; +https://github.com)"


# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(ts: dt.datetime) -> str:
    return ts.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp or date; naive values are taken as UTC."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        ts = dt.datetime.fromisoformat(text)
    except ValueError:
        try:
            ts = dt.datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=dt.timezone.utc)
    return ts


# --------------------------------------------------------------------------- #
# JSON I/O
# --------------------------------------------------------------------------- #
def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, obj: Any, compact: bool = False) -> None:
    """Write JSON atomically so an interrupted run never leaves a broken file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        if compact:
            json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def load_config(name: str) -> Any:
    return load_json(CONFIG_DIR / name)


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Http:
    """A small wrapper around `requests` with retries and per-host pacing."""

    def __init__(self, timeout: float = 30.0, min_interval: dict[str, float] | None = None):
        self.session = requests.Session()
        # Retry rate limits / server errors patiently, but give up quickly on dead hosts.
        retry = Retry(
            total=4,
            connect=1,
            read=1,
            other=1,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET",),
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.session.mount("http://", HTTPAdapter(max_retries=retry))
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.min_interval = min_interval or {}
        self._last_call: dict[str, float] = {}

    def _pace(self, url: str) -> None:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
        wait = self.min_interval.get(host, 0.0)
        if wait:
            elapsed = time.monotonic() - self._last_call.get(host, 0.0)
            if elapsed < wait:
                time.sleep(wait - elapsed)
            self._last_call[host] = time.monotonic()

    def get(self, url: str, params: dict | None = None, **kwargs) -> requests.Response:
        self._pace(url)
        resp = self.session.get(url, params=params, timeout=self.timeout, **kwargs)
        resp.raise_for_status()
        return resp


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(text: str | None) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def normalize(text: str) -> str:
    """Lower-case, map '&' to 'and', replace punctuation with spaces."""
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return _WS_RE.sub(" ", text).strip()


def title_key(title: str) -> str:
    """Stable identity for a paper across sources (arXiv vs. OpenAlex)."""
    return hashlib.sha1(normalize(title).encode("utf-8")).hexdigest()[:16]


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])", text.strip())
    return [p.strip() for p in parts if p.strip()]
