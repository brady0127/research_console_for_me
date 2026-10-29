# Research Console

A personal research dashboard, hosted free on GitHub Pages and refreshed by GitHub Actions:

1. **Paper tracking.** For each research field ("track") you define, it searches arXiv and
   OpenAlex every day, filters and ranks the results, and writes a short **analysis report** for
   each selected paper: TL;DR, summary, key innovations, datasets used, and the **venue tier**
   (CCF / CORE based). New papers are pushed to you.
2. **Research-community briefings.** Every 3 days it gathers news from journals, lab blogs and
   community sources, writes an edited briefing, and pushes it to you.

Plus a **live literature search** (OpenAlex) with the same venue tiers, an in-browser **track
editor**, and **Atom feeds** for any feed reader.

```
GitHub Actions (daily, 01:37 UTC)                    GitHub Pages
┌───────────────────────────────────────────┐        ┌────────────────────────────┐
│ arXiv API ─┐                              │        │ Overview · Papers · Search │
│ OpenAlex ──┼─▶ filter ─▶ rank ─▶ analyse ─┼─ JSON ─▶ News · Tracks · Settings  │
│ RSS feeds ─┘    (venue tiers)   (Claude)  │        └────────────────────────────┘
│                    └─▶ email / Telegram / ntfy / Atom                          │
└───────────────────────────────────────────┘
```

## How the pipeline decides what to show you

| Step | What happens | Why |
|---|---|---|
| Retrieve | arXiv: keyword phrases in title/abstract within your arXiv categories, newest first. OpenAlex: published journal/conference articles from the last 21 days. | arXiv is the fastest signal; OpenAlex adds peer-reviewed work. |
| Precision guard | A paper must contain at least one track keyword in its **title or abstract** (hyphen/space and plural variants match); exclude terms remove it. | API search is fuzzy; this keeps tracks on topic. |
| Venue tier | Computed deterministically from `config/venues.json` (133 venues). For arXiv papers it reads `journal_ref` and comments such as "Accepted at NeurIPS 2026 (Spotlight)", **ignoring** "under review / submitted to" and marking workshops separately. | Tiers must be reproducible and auditable, so the LLM never assigns them. |
| Quality bar | Published papers must meet the track's `min_tier`; arXiv preprints are kept when `include_preprints` is on. Unranked venues are dropped unless `min_tier` is `any`. | Filters out predatory and off-field venues. |
| Rank | `score = keyword relevance (title ×3, abstract ×1, capped) + tier bonus + recency`. The top `max_papers` per track are reported; papers already reported are never repeated. | Transparent and tunable. |
| Analyse | Claude reads the abstract **plus the experimental sections of the arXiv HTML full text** and returns structured JSON. Datasets are only listed if named in the text; the report says whether they came from the full text or the abstract. | Abstracts often omit datasets; grounding avoids hallucinated benchmarks. |

**Tiers:** `T1` CCF-A / CORE A* / flagship journal · `T2` CCF-B / CORE A · `T3` CCF-C / CORE B ·
`WS` workshop · `PP` preprint · `NR` published but not in the table. When CCF and CORE disagree
the higher rank is used (e.g. ECCV is CCF-B but CORE A*, so T1). Entries with a `note` were
assigned manually. Please review `config/venues.json` for your field and extend it as needed.

Without an `ANTHROPIC_API_KEY` everything still runs: reports fall back to a transparent
extractive heuristic (marked as such in the UI).

## Setup (about 10 minutes)

1. **Merge this branch into `main`.** Scheduled workflows only run on the default branch.
2. **Enable GitHub Pages:** *Settings → Pages → Build and deployment → Source: GitHub Actions*.
   The site will be at `https://<user>.github.io/research_console_for_me/`. If you use a
   different URL, update `site_url` in `config/settings.json`.
3. **Add secrets** (*Settings → Secrets and variables → Actions → New repository secret*):

   | Purpose | Secrets |
   |---|---|
   | Analysis reports (recommended) | `ANTHROPIC_API_KEY` |
   | Email push | `SMTP_HOST`, `SMTP_PORT` (587 or 465), `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO`, optional `MAIL_FROM` |
   | Telegram push | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
   | Phone push via [ntfy](https://ntfy.sh) | `NTFY_TOPIC` (a long random topic name), optional `NTFY_SERVER` |
   | OpenAlex (optional) | `OPENALEX_API_KEY` |

   For Gmail, use `smtp.gmail.com`, port `587` and an
   [app password](https://support.google.com/accounts/answer/185833). A channel is active as soon
   as its secrets exist.
4. **Define your tracks** in `config/tracks.json`, or in the site's *Tracks* page (see below).
5. **Run it once:** *Actions → Update research console → Run workflow* (tick *force news* to get a
   briefing immediately).

### Editing tracks from the website

*Settings → GitHub connection* takes a
[fine-grained personal access token](https://github.com/settings/personal-access-tokens/new)
restricted to this repository with **Contents: read & write** and **Actions: read & write**.
The token stays in your browser's local storage and is only sent to `api.github.com`. With it,
the *Tracks* page saves edits straight to `config/tracks.json` and *Run now* starts the workflow.
Without it, edits can be exported as `tracks.json` and committed by hand.

## Configuration reference

`config/tracks.json` (one object per track)

| Field | Meaning |
|---|---|
| `keywords` | Phrases; a paper needs at least one in its title or abstract. Prefer specific phrases. |
| `exclude` | Phrases that remove a paper. |
| `arxiv_categories` | e.g. `cs.LG`, `cs.CL`, `stat.ML`; empty means all. |
| `sources` | `arxiv`, `openalex`. |
| `min_tier` | `T1`, `T2`, `T3` or `any`, applied to published venues. |
| `include_preprints` | Keep arXiv preprints and workshop papers. |
| `lookback_days` | arXiv window (OpenAlex uses `papers.openalex_lookback_days`). |
| `max_papers` | Reports per track per run. |

`config/settings.json`: LLM model and effort, archive size, news cadence (`news.cadence_days`,
default 3) and interest keywords used to rank news. `config/news_sources.json`: RSS/Atom feeds
with a category and weight; failing feeds are shown in the UI and skipped.

**Cost.** The default model is `claude-opus-5-5` at `effort: "low"`. A report reads roughly
3-5k input tokens (abstract plus experimental sections), so about 20 papers a day plus a briefing
every three days typically costs on the order of $0.5-1 per day. Lower `max_papers`, set
`fulltext_for_datasets: false`, or change `llm.model` to reduce it.

## Local use

```bash
pip install -r requirements.txt
python -m console run --no-notify     # fetch + analyse (uses ANTHROPIC_API_KEY if set)
python -m console serve               # http://127.0.0.1:8000
python -m pytest -q                   # offline tests (fixtures, no network)
```

`python -m console run --only papers`, `--only news`, `--force-news` and `--offline` (heuristic
analysis) are also available.

## Repository layout

```
config/            tracks, venue tiers, news sources, settings
console/           Python pipeline (sources/, venues, analysis, papers, news, notify, feeds)
site/              static front end (index.html, assets/) and generated data/ + feeds/
state/             de-duplication state (papers and news already reported)
tests/             offline tests with fixtures
.github/workflows/ update (daily pipeline), deploy (Pages), tests
```

## Private repository

GitHub Pages can publish from a private repository only on GitHub Pro, Team or Enterprise
(Pro is free for students via the [GitHub Student Developer Pack](https://education.github.com/pack)).
The published site itself is always reachable by anyone with the URL. Choices:

* **Pro / Education:** keep the repository private and follow the setup above.
* **Make the repository public:** it contains only code and public bibliographic data; secrets
  and your GitHub token never enter it.
* **No Pages:** add the repository *variable* `DEPLOY_PAGES` = `false` (*Settings → Secrets and
  variables → Actions → Variables*). The daily pipeline and push notifications keep working; view
  the console locally with `git pull && python -m console serve`.

Private repositories also consume GitHub Actions minutes (2,000/month on Free); a daily run takes
roughly 5-15 minutes.

## Notes

* GitHub Pages sites are public even when they are not indexed (`noindex` is set). The site holds
  only public bibliographic data; tokens and secrets never enter the repository.
* GitHub disables scheduled workflows after 60 days without repository activity; the daily data
  commits keep it active.
* Data sources: [arXiv API](https://info.arxiv.org/help/api/), [OpenAlex](https://openalex.org)
  (CC0). Thank you to arXiv for use of its open access interoperability.
