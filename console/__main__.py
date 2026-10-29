"""Command-line entry point.

    python -m console run                 # papers + news (news only if due)
    python -m console run --only papers   # just the paper tracker
    python -m console run --force-news    # publish a briefing even if not due
    python -m console sync                # copy config into the site for the UI
    python -m console serve               # sync, then serve ./site on localhost
"""

from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import logging
import shutil
import sys

from . import feeds, notify
from .analysis import make_engine
from .common import CONFIG_DIR, DATA_DIR, LOG, iso, load_config, load_json, parse_iso, save_json, utcnow
from .news import INDEX_PATH, NEWS_DIR, NewsPipeline
from .papers import PAPERS_PATH, PaperPipeline

META_PATH = DATA_DIR / "meta.json"
SYNCED_CONFIGS = ("tracks.json", "venues.json", "news_sources.json", "settings.json")


def sync_config() -> None:
    target = DATA_DIR / "config"
    target.mkdir(parents=True, exist_ok=True)
    for name in SYNCED_CONFIGS:
        shutil.copyfile(CONFIG_DIR / name, target / name)


def update_meta(settings: dict, engine_name: str, paper_result: dict | None,
                news_result: dict | None, notifications: dict) -> None:
    now = utcnow()
    meta = load_json(META_PATH, {}) or {}
    meta["generated_at"] = iso(now)
    meta["channels"] = notify.active_channels()
    meta["llm"] = {"engine": engine_name, "model": settings["llm"].get("model")}
    run = {"time": iso(now), "engine": engine_name, "notifications": notifications}

    if paper_result is not None:
        meta["papers"] = {
            "last_run": paper_result["time"],
            "new_count": len(paper_result["new_papers"]),
            "tracks": paper_result["tracks"],
        }
        run["papers"] = {"new": len(paper_result["new_papers"]),
                         "errors": [e for t in paper_result["tracks"] for e in t["errors"]]}

    index = load_json(INDEX_PATH, {"issues": []})
    cadence = settings["news"].get("cadence_days", 3)
    if index["issues"]:
        last = parse_iso(index["issues"][0]["generated_at"])
        meta["news"] = {"last_issue": index["issues"][0]["id"], "last_time": iso(last),
                        "next_due": iso(last + dt.timedelta(days=cadence)), "cadence_days": cadence}
    if news_result is not None:
        if news_result.get("skipped"):
            run["news"] = {"published": False, "reason": "no items"}
        else:
            run["news"] = {"published": True, "issue": news_result["id"],
                           "items": len(news_result["items"]),
                           "failed_sources": [s["name"] for s in news_result["sources"] if not s["ok"]]}
        meta.setdefault("news", {})["sources"] = news_result["sources"]

    meta["runs"] = ([run] + meta.get("runs", []))[:30]
    save_json(META_PATH, meta)


def cmd_run(args) -> int:
    settings = load_config("settings.json")
    site_url = settings["site_url"].rstrip("/") + "/"
    engine = make_engine(settings["llm"], offline=args.offline)
    LOG.info("Analysis engine: %s", engine.name)
    notifications: dict = {}
    paper_result = news_result = None
    track_names = {}

    if args.only in (None, "papers"):
        tracks = load_config("tracks.json")["tracks"]
        track_names = {t["id"]: t["name"] for t in tracks}
        paper_result = PaperPipeline(settings, tracks, engine).run()
        archive = load_json(PAPERS_PATH, {"papers": []})["papers"]
        feeds.write_papers_feed(archive, site_url)
        new = paper_result["new_papers"]
        if new and not args.no_notify:
            notifications["papers"] = notify.dispatch(
                f"Research Console: {len(new)} new papers",
                notify.papers_html(new, track_names, site_url),
                notify.papers_text(new, site_url),
                f"{site_url}#/papers",
            )

    if args.only in (None, "news"):
        news_result = NewsPipeline(settings, load_config("news_sources.json"), engine).run(
            force=args.force_news)
        if news_result and not news_result.get("skipped"):
            index = load_json(INDEX_PATH, {"issues": []})["issues"][:20]
            issues = [load_json(NEWS_DIR / "issues" / f"{i['id']}.json") for i in index]
            feeds.write_news_feed([i for i in issues if i], site_url)
            if not args.no_notify:
                notifications["news"] = notify.dispatch(
                    f"Research briefing: {news_result['headline']}",
                    notify.news_html(news_result, site_url),
                    notify.news_text(news_result, site_url),
                    f"{site_url}#/news",
                )

    update_meta(settings, engine.name, paper_result, news_result, notifications)
    sync_config()
    return 0


def cmd_serve(args) -> int:
    sync_config()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(DATA_DIR.parent))
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Serving the console at http://127.0.0.1:{args.port}/  (Ctrl+C to stop)")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="console", description="Research Console pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="fetch, analyse, publish and notify")
    run.add_argument("--only", choices=["papers", "news"], help="run a single job")
    run.add_argument("--force-news", action="store_true", help="publish a briefing even if not due")
    run.add_argument("--offline", action="store_true", help="skip the LLM; use heuristic analysis")
    run.add_argument("--no-notify", action="store_true", help="do not send push notifications")
    run.set_defaults(func=cmd_run)
    sub.add_parser("sync", help="copy config files into site/data/config").set_defaults(
        func=lambda _: sync_config() or 0)
    serve = sub.add_parser("serve", help="serve the site locally")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
