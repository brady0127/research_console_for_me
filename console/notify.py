"""Push notifications. A channel is active when its secrets are present.

Email     SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASSWORD, MAIL_TO [, MAIL_FROM]
Telegram  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
ntfy      NTFY_TOPIC [, NTFY_SERVER (default https://ntfy.sh)]
"""

from __future__ import annotations

import html
import os
import smtplib
from email.message import EmailMessage

import requests

from .common import LOG, truncate

TIER_COLORS = {"T1": "#0f766e", "T2": "#2563eb", "T3": "#7c3aed", "WS": "#b45309",
               "PP": "#64748b", "NR": "#64748b"}


def active_channels() -> dict[str, bool]:
    env = os.environ
    return {
        "email": all(env.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO")),
        "telegram": all(env.get(k) for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")),
        "ntfy": bool(env.get("NTFY_TOPIC")),
    }


# --------------------------------------------------------------------------- #
# Message builders
# --------------------------------------------------------------------------- #
def papers_html(papers: list[dict], tracks: dict[str, str], site_url: str) -> str:
    e = html.escape
    rows = []
    for p in papers:
        a = p.get("analysis", {})
        v = p["venue"]
        color = TIER_COLORS.get(v["tier"], "#64748b")
        innovations = "".join(f"<li>{e(x)}</li>" for x in a.get("innovations", []))
        datasets = ", ".join(a.get("datasets", [])) or "Not specified in available text"
        track_names = ", ".join(tracks.get(t, t) for t in p.get("tracks", []))
        rows.append(f"""
<div style="border:1px solid #e2e8f0;border-radius:10px;padding:16px 18px;margin:0 0 14px">
  <div style="font-size:12px;color:#64748b;margin-bottom:6px">
    <span style="background:{color};color:#fff;border-radius:4px;padding:1px 6px;font-weight:600">{e(v['tier'])}</span>
    &nbsp;{e(v['label'])} &middot; {e(track_names)}
  </div>
  <a href="{e(p['url'] or '')}" style="font-size:16px;font-weight:600;color:#0f172a;text-decoration:none">{e(p['title'])}</a>
  <div style="font-size:12px;color:#64748b;margin:4px 0 10px">{e(', '.join(p['authors'][:6]))}{' et al.' if len(p['authors']) > 6 else ''}</div>
  <p style="margin:0 0 8px;font-size:14px;color:#0f172a"><b>TL;DR</b> {e(a.get('tldr', ''))}</p>
  <p style="margin:0 0 8px;font-size:14px;color:#334155">{e(a.get('summary', ''))}</p>
  <div style="font-size:14px;color:#334155"><b>Key innovations</b><ul style="margin:4px 0 8px 18px;padding:0">{innovations}</ul></div>
  <div style="font-size:13px;color:#334155"><b>Datasets</b> {e(datasets)}</div>
</div>""")
    return f"""<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:720px;margin:auto">
<h2 style="font-size:20px;color:#0f172a">{len(papers)} new papers</h2>
{''.join(rows)}
<p style="font-size:13px"><a href="{e(site_url)}#/papers">Open the Research Console &rarr;</a></p></div>"""


def news_html(issue: dict, site_url: str) -> str:
    e = html.escape
    items = {it["id"]: it for it in issue["items"]}
    blocks = []
    for section in issue["sections"]:
        points = []
        for pt in section["points"]:
            links = " ".join(
                f'<a href="{e(items[i]["link"])}" style="color:#2563eb">[{e(items[i]["source_name"])}]</a>'
                for i in pt["item_ids"] if i in items
            )
            points.append(f"<li style='margin-bottom:6px'>{e(pt['text'])} {links}</li>")
        blocks.append(f"<h3 style='font-size:15px;margin:18px 0 6px;color:#0f172a'>{e(section['theme'])}</h3>"
                      f"<ul style='margin:0 0 0 18px;padding:0;font-size:14px;color:#334155'>{''.join(points)}</ul>")
    return f"""<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:720px;margin:auto">
<h2 style="font-size:20px;color:#0f172a">{e(issue['headline'])}</h2>
<p style="font-size:14px;color:#334155">{e(issue['overview'])}</p>{''.join(blocks)}
<p style="font-size:13px;margin-top:20px"><a href="{e(site_url)}#/news">Read the full briefing &rarr;</a></p></div>"""


def papers_text(papers: list[dict], site_url: str, limit: int = 8) -> str:
    lines = [f"{len(papers)} new papers"]
    for p in papers[:limit]:
        lines.append(f"\n[{p['venue']['tier']}] {p['title']}\n{truncate(p.get('analysis', {}).get('tldr', ''), 200)}\n{p['url']}")
    if len(papers) > limit:
        lines.append(f"\n…and {len(papers) - limit} more")
    lines.append(f"\n{site_url}#/papers")
    return "\n".join(lines)


def news_text(issue: dict, site_url: str) -> str:
    return f"{issue['headline']}\n\n{truncate(issue['overview'], 700)}\n\n{site_url}#/news"


# --------------------------------------------------------------------------- #
# Senders
# --------------------------------------------------------------------------- #
def send_email(subject: str, html_body: str, text_body: str) -> None:
    env = os.environ
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env.get("MAIL_FROM") or env["SMTP_USER"]
    msg["To"] = env["MAIL_TO"]
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    port = int(env.get("SMTP_PORT") or 587)
    if port == 465:
        with smtplib.SMTP_SSL(env["SMTP_HOST"], port, timeout=30) as smtp:
            smtp.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(env["SMTP_HOST"], port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(env["SMTP_USER"], env["SMTP_PASSWORD"])
            smtp.send_message(msg)


def send_telegram(text: str) -> None:
    env = os.environ
    resp = requests.post(
        f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={"chat_id": env["TELEGRAM_CHAT_ID"], "text": text[:4000], "disable_web_page_preview": True},
        timeout=30,
    )
    resp.raise_for_status()


def send_ntfy(title: str, text: str, click_url: str) -> None:
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    resp = requests.post(
        server,
        json={"topic": os.environ["NTFY_TOPIC"], "title": title, "message": text[:3800],
              "click": click_url, "tags": ["books"]},
        timeout=30,
    )
    resp.raise_for_status()


def dispatch(subject: str, html_body: str, text_body: str, click_url: str) -> dict[str, str]:
    """Send through every active channel; failures are logged, never raised."""
    results = {}
    channels = active_channels()
    senders = {
        "email": lambda: send_email(subject, html_body, text_body),
        "telegram": lambda: send_telegram(f"{subject}\n\n{text_body}"),
        "ntfy": lambda: send_ntfy(subject, text_body, click_url),
    }
    for name, enabled in channels.items():
        if not enabled:
            continue
        try:
            senders[name]()
            results[name] = "sent"
        except Exception as exc:
            LOG.error("Notification via %s failed: %s", name, exc)
            results[name] = f"failed: {str(exc)[:160]}"
    return results
