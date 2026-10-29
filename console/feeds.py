"""Atom feeds, so any feed reader can subscribe to the console."""

from __future__ import annotations

from xml.sax.saxutils import escape

from .common import FEED_DIR, iso, utcnow


def _entry(entry_id: str, title: str, link: str, updated: str, html_content: str) -> str:
    return (
        "  <entry>\n"
        f"    <id>{escape(entry_id)}</id>\n"
        f"    <title>{escape(title)}</title>\n"
        f'    <link href="{escape(link)}"/>\n'
        f"    <updated>{escape(updated)}</updated>\n"
        f'    <content type="html">{escape(html_content)}</content>\n'
        "  </entry>\n"
    )


def _write(name: str, title: str, site_url: str, entries: list[str]) -> None:
    FEED_DIR.mkdir(parents=True, exist_ok=True)
    feed_url = f"{site_url}feeds/{name}"
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <id>{escape(feed_url)}</id>\n"
        f"  <title>{escape(title)}</title>\n"
        f'  <link href="{escape(site_url)}"/>\n'
        f'  <link rel="self" href="{escape(feed_url)}"/>\n'
        f"  <updated>{iso(utcnow())}</updated>\n"
        + "".join(entries)
        + "</feed>\n"
    )
    (FEED_DIR / name).write_text(xml, encoding="utf-8")


def write_papers_feed(papers: list[dict], site_url: str, limit: int = 60) -> None:
    entries = []
    for p in papers[:limit]:
        a = p.get("analysis", {})
        body = (
            f"<p><b>[{p['venue']['tier']}] {escape(p['venue']['label'])}</b></p>"
            f"<p><b>TL;DR</b> {escape(a.get('tldr', ''))}</p>"
            f"<p>{escape(a.get('summary', ''))}</p>"
            "<ul>" + "".join(f"<li>{escape(x)}</li>" for x in a.get("innovations", [])) + "</ul>"
            f"<p><b>Datasets:</b> {escape(', '.join(a.get('datasets', [])) or 'n/a')}</p>"
        )
        entries.append(_entry(p["id"], p["title"], p["url"] or site_url,
                              p.get("fetched_at") or iso(utcnow()), body))
    _write("papers.xml", "Research Console - Papers", site_url, entries)


def write_news_feed(issues: list[dict], site_url: str) -> None:
    entries = []
    for issue in issues:
        body = f"<p>{escape(issue['overview'])}</p>" + "".join(
            f"<h3>{escape(s['theme'])}</h3><ul>"
            + "".join(f"<li>{escape(pt['text'])}</li>" for pt in s["points"]) + "</ul>"
            for s in issue["sections"]
        )
        entries.append(_entry(f"news:{issue['id']}", issue["headline"],
                              f"{site_url}#/news/{issue['id']}", issue["generated_at"], body))
    _write("news.xml", "Research Console - Briefings", site_url, entries)
