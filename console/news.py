"""Research-community news: RSS/Atom aggregation and periodic briefings."""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib

import feedparser

from .common import (
    DATA_DIR, LOG, STATE_DIR, Http, clean_text, iso, load_json, normalize, parse_iso,
    save_json, truncate, utcnow,
)

NEWS_DIR = DATA_DIR / "news"
INDEX_PATH = NEWS_DIR / "index.json"
SEEN_PATH = STATE_DIR / "news_seen.json"
MAX_WINDOW_DAYS = 7
DUE_TOLERANCE = dt.timedelta(hours=3)  # absorbs GitHub Actions cron jitter


def item_id(link: str, title: str) -> str:
    return "n" + hashlib.sha1((link or title).encode("utf-8")).hexdigest()[:10]


def entry_time(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return dt.datetime.fromtimestamp(calendar.timegm(value), tz=dt.timezone.utc)
    return None


def parse_feed(content: bytes, source: dict) -> list[dict]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        title = clean_text(entry.get("title"))
        link = entry.get("link") or ""
        if not title:
            continue
        published = entry_time(entry)
        summary = clean_text(entry.get("summary") or entry.get("description") or "")
        items.append(
            {
                "id": item_id(link, title),
                "title": title,
                "link": link,
                "summary": truncate(summary, 600),
                "published": iso(published) if published else None,
                "source_id": source["id"],
                "source_name": source["name"],
                "category": source["category"],
            }
        )
    return items


def is_due(settings: dict, now: dt.datetime) -> tuple[bool, dt.datetime | None]:
    index = load_json(INDEX_PATH, {"issues": []})
    if not index["issues"]:
        return True, None
    last = parse_iso(index["issues"][0]["generated_at"])
    cadence = dt.timedelta(days=settings.get("news", {}).get("cadence_days", 3))
    return (last is None or now - last >= cadence - DUE_TOLERANCE), last


class NewsPipeline:
    def __init__(self, settings: dict, sources_cfg: dict, engine, http: Http | None = None,
                 now: dt.datetime | None = None):
        self.settings = settings
        self.cfg = settings.get("news", {})
        self.sources = sources_cfg["sources"]
        self.engine = engine
        self.http = http or Http(timeout=25)
        self.now = now or utcnow()

    def score(self, item: dict, weight: float) -> float:
        text = normalize(f"{item['title']} {item['summary']}")
        hits = sum(1 for kw in self.cfg.get("interest_keywords", [])
                   if f" {normalize(kw)} " in f" {text} ")
        published = parse_iso(item["published"]) or self.now
        age_days = max(0.0, (self.now - published).total_seconds() / 86400)
        recency = max(0.2, 1.0 - age_days / MAX_WINDOW_DAYS)
        return round(weight * (1.0 + 0.5 * min(hits, 3)) * recency, 3)

    def collect(self, since: dt.datetime, seen: dict) -> tuple[list[dict], list[dict]]:
        items, status = [], []
        per_source = self.cfg.get("max_items_per_source", 12)
        for source in self.sources:
            if not source.get("enabled", True):
                continue
            try:
                resp = self.http.get(source["url"])
                parsed = parse_feed(resp.content, source)
            except Exception as exc:
                LOG.error("News source %s failed: %s", source["id"], exc)
                status.append({"id": source["id"], "name": source["name"], "ok": False,
                               "count": 0, "error": str(exc)[:200]})
                continue
            fresh = []
            for item in parsed:
                if item["id"] in seen:
                    continue
                published = parse_iso(item["published"])
                if published is not None and published < since:
                    continue
                if published is not None and published > self.now + dt.timedelta(days=1):
                    continue  # malformed future dates
                item["score"] = self.score(item, source.get("weight", 1.0))
                fresh.append(item)
            fresh.sort(key=lambda x: -x["score"])
            fresh = fresh[:per_source]
            items += fresh
            status.append({"id": source["id"], "name": source["name"], "ok": True,
                           "count": len(fresh), "error": None})
        # Same story syndicated by several feeds: keep the highest-scoring copy.
        by_title: dict[str, dict] = {}
        for item in sorted(items, key=lambda x: -x["score"]):
            by_title.setdefault(normalize(item["title"]), item)
        return sorted(by_title.values(), key=lambda x: -x["score"]), status

    def run(self, force: bool = False) -> dict | None:
        due, last = is_due(self.settings, self.now)
        if not (due or force):
            LOG.info("News briefing not due yet (last issue %s).", last)
            return None
        # Cover everything since the previous issue (the first issue looks back a full week).
        earliest = self.now - dt.timedelta(days=MAX_WINDOW_DAYS)
        since = max(last, earliest) if last else earliest
        seen: dict = load_json(SEEN_PATH, {})
        items, status = self.collect(since, seen)
        if not items:
            LOG.warning("No news items collected; skipping issue.")
            return {"skipped": True, "sources": status}

        brief_items = items[: self.cfg.get("max_items_for_briefing", 90)]
        period = f"{since.date().isoformat()} to {self.now.date().isoformat()}"
        try:
            briefing = self.engine.write_briefing(brief_items, period)
        except Exception as exc:
            from .analysis import HeuristicEngine

            LOG.warning("Briefing generation failed (%s); using heuristic briefing.", exc)
            briefing = HeuristicEngine().write_briefing(brief_items, period)
        valid = {it["id"] for it in items}
        for section in briefing["sections"]:
            for point in section["points"]:
                point["item_ids"] = [i for i in point["item_ids"] if i in valid]
        briefing["top_picks"] = [i for i in briefing["top_picks"] if i in valid]

        issue_id = self.now.strftime("%Y-%m-%d")
        issue = {
            "id": issue_id,
            "generated_at": iso(self.now),
            "period_start": iso(since),
            "period_end": iso(self.now),
            **briefing,
            "items": items,
            "sources": status,
        }
        save_json(NEWS_DIR / "issues" / f"{issue_id}.json", issue, compact=True)

        index = load_json(INDEX_PATH, {"issues": []})
        index["issues"] = [i for i in index["issues"] if i["id"] != issue_id]
        index["issues"].insert(0, {"id": issue_id, "generated_at": iso(self.now),
                                   "headline": briefing["headline"], "item_count": len(items)})
        keep = self.cfg.get("issues_to_keep", 60)
        for stale in index["issues"][keep:]:
            (NEWS_DIR / "issues" / f"{stale['id']}.json").unlink(missing_ok=True)
        index["issues"] = index["issues"][:keep]
        save_json(INDEX_PATH, index)

        for item in items:
            seen[item["id"]] = iso(self.now)
        cutoff = self.now - dt.timedelta(days=60)
        seen = {k: v for k, v in seen.items() if (parse_iso(v) or self.now) >= cutoff}
        save_json(SEEN_PATH, seen, compact=True)
        return issue
