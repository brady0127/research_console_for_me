/* Research Console - single-page front end (no build step, no framework). */
(function () {
  "use strict";

  // ------------------------------------------------------------------------ //
  // Utilities
  // ------------------------------------------------------------------------ //
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : "#");

  const store = {
    get(key, fallback) {
      try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); }
      catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
    },
    remove(key) { try { localStorage.removeItem(key); } catch (e) { /* ignore */ } },
  };

  const ICON = {
    star: '<svg viewBox="0 0 24 24"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
    doc: '<svg viewBox="0 0 24 24"><path d="M7 3h7l5 5v13H7zM14 3v5h5"/></svg>',
    ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6m0-6-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
    quote: '<svg viewBox="0 0 24 24"><path d="M7 7h4v4c0 3-1.5 5-4 6m8-10h4v4c0 3-1.5 5-4 6"/></svg>',
    down: '<svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>',
    up: '<svg viewBox="0 0 24 24"><path d="m6 15 6-6 6 6"/></svg>',
    search: '<svg viewBox="0 0 24 24"><path d="M11 18a7 7 0 1 1 0-14 7 7 0 0 1 0 14zm9 3-4.3-4.3"/></svg>',
    plus: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    play: '<svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z"/></svg>',
    edit: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4"/></svg>',
    copy: '<svg viewBox="0 0 24 24"><path d="M9 9h10v10H9zM5 15V5h10"/></svg>',
    trash: '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
    download: '<svg viewBox="0 0 24 24"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 19h14"/></svg>',
    feed: '<svg viewBox="0 0 24 24"><path d="M5 19h.01M5 12a7 7 0 0 1 7 7M5 5a14 14 0 0 1 14 14"/></svg>',
  };

  const TIER_INFO = {
    T1: "Top tier: CCF-A, CORE A*, or flagship journal",
    T2: "Strong: CCF-B or CORE A",
    T3: "Solid: CCF-C or CORE B",
    WS: "Workshop paper at a recognised venue",
    PP: "Preprint: no acceptance found",
    NR: "Published, venue not in the curated table",
  };
  const TIER_RANK = { T1: 5, T2: 4, T3: 3, WS: 2, PP: 1, NR: 0 };

  const tierBadge = (tier) =>
    `<span class="tier tier-${esc(tier)}" title="${esc(TIER_INFO[tier] || "")}">${esc(tier)}</span>`;

  function fmtDate(iso, opts) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return esc(iso);
    return d.toLocaleDateString("en-US", opts || { month: "short", day: "numeric", year: "numeric" });
  }

  function relTime(iso) {
    if (!iso) return "never";
    const diff = (new Date(iso) - Date.now()) / 1000;
    const abs = Math.abs(diff);
    const units = [["day", 86400], ["hour", 3600], ["minute", 60]];
    const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
    for (const [unit, secs] of units) {
      if (abs >= secs || unit === "minute") return rtf.format(Math.round(diff / secs), unit);
    }
    return "";
  }

  function dayKey(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "Unknown date" : d.toLocaleDateString("en-CA"); // YYYY-MM-DD, local time
  }

  function authorsLine(authors, max = 6) {
    if (!authors || !authors.length) return "";
    const shown = authors.slice(0, max).map(esc).join(", ");
    return authors.length > max ? `${shown} <span class="muted">+${authors.length - max}</span>` : shown;
  }

  function toast(message) {
    const el = $("#toast");
    el.textContent = message;
    el.classList.add("show");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove("show"), 3200);
  }

  async function copyText(text, message) {
    try { await navigator.clipboard.writeText(text); toast(message || "Copied to clipboard"); }
    catch (e) { window.prompt("Copy:", text); }
  }

  function download(name, text, type) {
    const blob = new Blob([text], { type: type || "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  async function getJSON(url) {
    try {
      const resp = await fetch(url, { cache: "no-cache" });
      if (!resp.ok) return null;
      return await resp.json();
    } catch (e) {
      return null;
    }
  }

  function bibtex(p) {
    const year = (p.published || "").slice(0, 4) || "n.d.";
    const last = ((p.authors && p.authors[0]) || "anon").split(" ").pop().toLowerCase().replace(/[^a-z]/g, "");
    const word = (p.title || "paper").toLowerCase().split(/\s+/).find((w) => w.length > 3) || "paper";
    const key = `${last}${year}${word.replace(/[^a-z]/g, "")}`;
    const venue = p.venue && p.venue.status !== "preprint" ? p.venue.label : null;
    const lines = [
      `@article{${key},`,
      `  title   = {${p.title}},`,
      `  author  = {${(p.authors || []).join(" and ")}},`,
      `  year    = {${year}},`,
      venue ? `  journal = {${venue}},` : p.arxiv_id ? `  journal = {arXiv preprint arXiv:${p.arxiv_id}},` : null,
      p.doi ? `  doi     = {${p.doi}},` : null,
      p.url ? `  url     = {${p.url}},` : null,
      "}",
    ];
    return lines.filter(Boolean).join("\n");
  }

  // ------------------------------------------------------------------------ //
  // State
  // ------------------------------------------------------------------------ //
  const state = {
    papers: [],
    meta: {},
    newsIndex: { issues: [] },
    issues: {},
    tracks: [],
    tracksSha: null,
    tracksDirty: false,
    venues: null,
    resolver: null,
    settings: {},
    read: new Set(store.get("rc.read", [])),
    starred: new Set(store.get("rc.starred", [])),
    github: store.get("rc.github", null),
    ui: {
      papers: { q: "", track: "all", tiers: new Set(["T1", "T2", "T3", "WS", "PP", "NR"]),
                range: "all", sort: "score", unread: false, starred: false, limit: 40 },
      expanded: new Set(),
      newsCategory: "all",
      search: { q: "", from: "", to: "", type: "any", minTier: "any", sort: "relevance", oa: false,
                page: 1, results: [], count: 0, loading: false, error: null },
      trackPrefill: null,
    },
  };

  const saveRead = () => store.set("rc.read", Array.from(state.read).slice(-5000));
  const saveStarred = () => store.set("rc.starred", Array.from(state.starred));

  async function loadData() {
    const [papers, meta, newsIndex, tracks, venues, settings] = await Promise.all([
      getJSON("data/papers.json"),
      getJSON("data/meta.json"),
      getJSON("data/news/index.json"),
      getJSON("data/config/tracks.json"),
      getJSON("data/config/venues.json"),
      getJSON("data/config/settings.json"),
    ]);
    state.papers = (papers && papers.papers) || [];
    state.meta = meta || {};
    state.newsIndex = newsIndex || { issues: [] };
    state.tracks = (tracks && tracks.tracks) || [];
    state.venues = venues;
    state.resolver = venues && window.VenueResolver ? new window.VenueResolver(venues) : null;
    state.settings = settings || {};
  }

  const trackName = (id) => (state.tracks.find((t) => t.id === id) || {}).name || id;
  const latestRunId = () => (state.papers[0] || {}).run_id;

  function updateChrome() {
    const unread = state.papers.filter((p) => !state.read.has(p.id)).length;
    const badge = $("#nav-unread");
    badge.hidden = unread === 0;
    badge.textContent = unread > 99 ? "99+" : String(unread);
    const gen = state.meta.generated_at;
    $("#status-line").innerHTML = gen ? `Updated ${esc(relTime(gen))}` : "No pipeline run yet";
  }

  // ------------------------------------------------------------------------ //
  // Overview
  // ------------------------------------------------------------------------ //
  function renderOverview() {
    const runId = latestRunId();
    const latest = state.papers.filter((p) => p.run_id === runId);
    const unread = state.papers.filter((p) => !state.read.has(p.id)).length;
    const active = state.tracks.filter((t) => t.enabled !== false);
    const news = state.meta.news || {};
    const lastIssue = state.newsIndex.issues[0];
    const hour = new Date().getHours();
    const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

    if (!state.papers.length && !lastIssue) {
      return `${pageHead(greeting, fmtDate(new Date().toISOString(), { weekday: "long", month: "long", day: "numeric" }))}
        <div class="card">${setupSteps()}</div>`;
    }

    const top = latest.slice().sort((a, b) => b.score - a.score).slice(0, 6);
    const topHtml = top.length
      ? `<ul class="list">${top.map((p) => `
          <li>
            <a class="t" href="#/papers" data-action="focus-paper" data-id="${esc(p.id)}">${esc(p.title)}</a>
            <div class="m">${tierBadge(p.venue.tier)}<span>${esc(p.venue.label)}</span>
              <span>·</span><span>${esc((p.tracks || []).map(trackName).join(", "))}</span></div>
          </li>`).join("")}</ul>`
      : `<div class="empty"><p>No new papers in the latest run.</p></div>`;

    const briefHtml = lastIssue
      ? `<div class="card-pad">
           <div class="eyebrow">${esc(fmtDate(lastIssue.generated_at))}</div>
           <div class="brief-head" style="margin-top:6px">${esc(lastIssue.headline)}</div>
           <p class="muted" id="ov-brief-overview" style="margin:10px 0 0">…</p>
         </div>`
      : `<div class="empty"><p>The first briefing will be published on the next scheduled run.</p></div>`;

    const errs = (state.meta.papers && state.meta.papers.tracks || []).flatMap((t) => t.errors || []);
    const failedSources = ((news.sources) || []).filter((s) => !s.ok);
    const ch = state.meta.channels || {};
    const chHtml = [["email", "Email"], ["telegram", "Telegram"], ["ntfy", "ntfy"]].map(([c, label]) =>
      `<span><i class="${ch[c] ? "dot-ok" : "dot-off"}"></i>${label}</span>`).join(" &nbsp; ");

    return `
      ${pageHead(greeting, fmtDate(new Date().toISOString(), { weekday: "long", month: "long", day: "numeric" }))}
      <div class="grid grid-kpi" style="margin-bottom:16px">
        ${kpi("New papers", latest.length, state.meta.papers ? `Last run ${relTime(state.meta.papers.last_run)}` : "—")}
        ${kpi("Unread", unread, `${state.papers.length} in archive`)}
        ${kpi("Active tracks", active.length, active.map((t) => t.name).slice(0, 2).join(", ") + (active.length > 2 ? "…" : ""))}
        ${kpi("Next briefing", news.next_due ? relTime(news.next_due).replace(/^in /, "") : "—",
              news.cadence_days ? `Every ${news.cadence_days} days` : "Every 3 days")}
      </div>
      <div class="grid grid-2">
        <section class="card">
          <div class="card-head"><h2>Top papers from the latest run</h2><a class="link" href="#/papers">All papers →</a></div>
          ${topHtml}
        </section>
        <div class="stack">
          <section class="card">
            <div class="card-head"><h2>Latest briefing</h2><a class="link" href="#/news">Read →</a></div>
            ${briefHtml}
          </section>
          <section class="card">
            <div class="card-head"><h2>Pipeline status</h2></div>
            <div class="card-pad">
              <dl class="status-rows">
                <dt>Last run</dt><dd>${esc(state.meta.generated_at ? fmtDate(state.meta.generated_at, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—")}</dd>
                <dt>Analysis</dt><dd>${esc(engineLabel())}</dd>
                <dt>Push</dt><dd>${chHtml}</dd>
                <dt>Sources</dt><dd>${errs.length || failedSources.length
                  ? `<span class="note" title="${esc(errs.concat(failedSources.map((x) => x.name + ": " + x.error)).join("\n"))}">${
                      [errs.length ? `${errs.length} paper-source error${errs.length > 1 ? "s" : ""}` : "",
                       failedSources.length ? `${failedSources.length} news feed${failedSources.length > 1 ? "s" : ""} failing` : ""]
                        .filter(Boolean).join(", ")}</span>`
                  : '<i class="dot-ok"></i>All sources healthy'}</dd>
              </dl>
            </div>
          </section>
        </div>
      </div>`;
  }

  function engineLabel() {
    const llm = state.meta.llm || {};
    if (!llm.engine) return "—";
    return llm.engine === "claude" ? `Claude (${llm.model})` : "Heuristic (no API key)";
  }

  async function hydrateOverview() {
    const el = $("#ov-brief-overview");
    const last = state.newsIndex.issues[0];
    if (!el || !last) return;
    const issue = await loadIssue(last.id);
    if (issue && $("#ov-brief-overview")) {
      const text = issue.overview || "";
      el.textContent = text.length > 360 ? text.slice(0, 360).replace(/\s+\S*$/, "") + "…" : text;
    }
  }

  const kpi = (label, value, sub) => `
    <div class="card kpi"><div class="label">${esc(label)}</div>
      <div class="value">${esc(value)}</div><div class="sub">${esc(sub)}</div></div>`;

  const pageHead = (title, sub, actions) => `
    <header class="page-head">
      <div><h1>${esc(title)}</h1>${sub ? `<p>${esc(sub)}</p>` : ""}</div>
      ${actions ? `<div class="toolbar" style="margin:0">${actions}</div>` : ""}
    </header>`;

  function setupSteps() {
    return `<div class="card-pad">
      <h2 style="font-size:16px;margin-bottom:8px">Welcome to your Research Console</h2>
      <p class="muted" style="margin:0 0 14px">No data has been generated yet. To get the pipeline running:</p>
      <ol style="margin:0;padding-left:20px;line-height:1.9;color:var(--text-2)">
        <li>Define your research fields under <a href="#/tracks">Tracks</a> (or edit <span class="code">config/tracks.json</span>).</li>
        <li>Add the <span class="code">ANTHROPIC_API_KEY</span> repository secret for full analysis reports (optional).</li>
        <li>Add notification secrets (email, Telegram or ntfy) for push delivery (optional).</li>
        <li>Run the <b>Update research console</b> workflow from the Actions tab, or use <b>Run now</b> on the Tracks page.</li>
      </ol></div>`;
  }

  // ------------------------------------------------------------------------ //
  // Papers
  // ------------------------------------------------------------------------ //
  function filteredPapers() {
    const f = state.ui.papers;
    const q = f.q.trim().toLowerCase();
    const runId = latestRunId();
    const now = Date.now();
    const rangeDays = { "7d": 7, "30d": 30 }[f.range];
    let list = state.papers.filter((p) => {
      if (f.track !== "all" && !(p.tracks || []).includes(f.track)) return false;
      if (!f.tiers.has(p.venue.tier)) return false;
      if (f.unread && state.read.has(p.id)) return false;
      if (f.starred && !state.starred.has(p.id)) return false;
      if (f.range === "latest" && p.run_id !== runId) return false;
      if (rangeDays && now - new Date(p.fetched_at) > rangeDays * 86400e3) return false;
      if (q) {
        const a = p.analysis || {};
        const hay = [p.title, p.abstract, (p.authors || []).join(" "), p.venue.label,
                     (a.datasets || []).join(" "), (a.innovations || []).join(" ")].join(" ").toLowerCase();
        if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
      }
      return true;
    });
    const cmp = {
      score: (a, b) => b.score - a.score,
      newest: (a, b) => String(b.published).localeCompare(String(a.published)),
      tier: (a, b) => (TIER_RANK[b.venue.tier] - TIER_RANK[a.venue.tier]) || (b.score - a.score),
    }[f.sort];
    list.sort((a, b) => String(b.fetched_at).localeCompare(String(a.fetched_at)) || cmp(a, b));
    return list;
  }

  function renderPapers() {
    const f = state.ui.papers;
    if (!state.papers.length) {
      return `${pageHead("Papers", "Tracked papers with analysis reports")}
        <div class="card">${setupSteps()}</div>`;
    }
    const all = filteredPapers();
    const shown = all.slice(0, f.limit);
    const counts = {};
    state.papers.forEach((p) => { counts[p.venue.tier] = (counts[p.venue.tier] || 0) + 1; });

    const groups = [];
    for (const p of shown) {
      const k = dayKey(p.fetched_at);
      if (!groups.length || groups[groups.length - 1].key !== k) groups.push({ key: k, items: [] });
      groups[groups.length - 1].items.push(p);
    }
    const dayCounts = {};
    all.forEach((p) => { const k = dayKey(p.fetched_at); dayCounts[k] = (dayCounts[k] || 0) + 1; });

    const listHtml = groups.length
      ? groups.map((g) => `
          <div class="day-head"><h2>${esc(fmtDate(g.key + "T12:00:00", { weekday: "short", month: "short", day: "numeric", year: "numeric" }))}</h2>
            <span>${dayCounts[g.key]} paper${dayCounts[g.key] === 1 ? "" : "s"}</span></div>
          ${g.items.map(paperCard).join("")}`).join("")
      : `<div class="card empty"><h2>No papers match these filters</h2><p>Try widening the tier or date filters.</p></div>`;

    return `
      ${pageHead("Papers", `${all.length} of ${state.papers.length} papers`,
        `<button class="btn btn-sm" data-action="mark-all-read">${ICON.check} Mark shown as read</button>`)}
      <div class="toolbar">
        <div class="search-box grow">${ICON.search}
          <input class="input" id="pf-q" type="search" placeholder="Filter by title, author, dataset, venue…" value="${esc(f.q)}" aria-label="Filter papers"></div>
        <select class="select" id="pf-track" aria-label="Track">
          <option value="all">All tracks</option>
          ${state.tracks.map((t) => `<option value="${esc(t.id)}" ${f.track === t.id ? "selected" : ""}>${esc(t.name)}</option>`).join("")}
        </select>
        <select class="select" id="pf-range" aria-label="Date range">
          ${[["all", "Any time"], ["latest", "Latest run"], ["7d", "Past 7 days"], ["30d", "Past 30 days"]]
            .map(([v, l]) => `<option value="${v}" ${f.range === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <select class="select" id="pf-sort" aria-label="Sort">
          ${[["score", "Sort: relevance"], ["newest", "Sort: newest"], ["tier", "Sort: venue tier"]]
            .map(([v, l]) => `<option value="${v}" ${f.sort === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
      </div>
      <div class="filter-row">
        <div class="filter-group"><span class="label">Tier</span>
          ${["T1", "T2", "T3", "WS", "PP", "NR"].map((t) => `
            <button class="chip" type="button" data-action="tier" data-tier="${t}" aria-pressed="${f.tiers.has(t)}" title="${esc(TIER_INFO[t])}">
              ${t}<span class="n">${counts[t] || 0}</span></button>`).join("")}
        </div>
        <div class="filter-group">
          <button class="chip" type="button" data-action="toggle-unread" aria-pressed="${f.unread}">Unread only</button>
          <button class="chip" type="button" data-action="toggle-starred" aria-pressed="${f.starred}">${ICON.star.replace("<svg", '<svg width="13" height="13" style="fill:none;stroke:currentColor;stroke-width:1.8"')} Starred</button>
        </div>
      </div>
      <div id="paper-list">${listHtml}</div>
      ${all.length > f.limit ? `<div class="more"><button class="btn" data-action="more-papers">Show more (${all.length - f.limit} remaining)</button></div>` : ""}`;
  }

  function paperCard(p) {
    const a = p.analysis || {};
    const open = state.ui.expanded.has(p.id);
    const read = state.read.has(p.id);
    const star = state.starred.has(p.id);
    const date = p.published ? fmtDate(p.published) : "";
    return `
      <article class="card paper ${read ? "is-read" : ""}" data-id="${esc(p.id)}" id="paper-${esc(p.id.replace(/[^\w-]/g, "_"))}">
        <div class="paper-meta">
          ${tierBadge(p.venue.tier)}
          <span class="venue">${esc(p.venue.label)}</span>
          ${date ? `<span class="dot">${esc(date)}</span>` : ""}
          ${(p.tracks || []).map((t) => `<span class="tag tag-accent">${esc(trackName(t))}</span>`).join("")}
        </div>
        <h3 class="paper-title"><a href="${safeUrl(p.url)}" target="_blank" rel="noopener" data-action="open-paper">${esc(p.title)}</a></h3>
        <div class="paper-authors">${authorsLine(p.authors)}</div>
        ${a.tldr ? `<p class="tldr"><b>TL;DR</b>${esc(a.tldr)}</p>` : ""}
        <div class="paper-actions">
          <button class="btn btn-ghost" data-action="toggle-report" aria-expanded="${open}">${open ? ICON.up : ICON.down} ${open ? "Hide report" : "Analysis report"}</button>
          ${p.pdf_url ? `<a class="btn btn-ghost" href="${safeUrl(p.pdf_url)}" target="_blank" rel="noopener">${ICON.doc} PDF</a>` : ""}
          <a class="btn btn-ghost" href="${safeUrl(p.url)}" target="_blank" rel="noopener">${ICON.ext} ${p.source === "arxiv" ? "arXiv" : "Source"}</a>
          <button class="btn btn-ghost" data-action="cite">${ICON.quote} Cite</button>
          <span class="spacer"></span>
          <button class="btn btn-ghost ${star ? "is-on" : ""}" data-action="star" aria-pressed="${star}" title="Star">${ICON.star}</button>
          <button class="btn btn-ghost" data-action="read" title="${read ? "Mark as unread" : "Mark as read"}">${ICON.check} ${read ? "Read" : "Mark read"}</button>
        </div>
        ${open ? reportHtml(p) : ""}
      </article>`;
  }

  function reportHtml(p) {
    const a = p.analysis || {};
    const v = p.venue || {};
    const rel = Number(a.relevance) || 0;
    const ranks = [v.ccf ? `CCF-${v.ccf}` : null, v.core ? `CORE ${v.core}` : null].filter(Boolean).join(" · ");
    return `
      <div class="report">
        <div class="stack" style="gap:16px">
          <div><h3>Summary</h3><p>${esc(a.summary || "—")}</p></div>
          <div><h3>Key innovations</h3>
            ${(a.innovations || []).length ? `<ul>${a.innovations.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : '<p class="muted">Not identified.</p>'}
          </div>
          ${a.note ? `<p class="note">${esc(a.note)}</p>` : ""}
        </div>
        <div class="side">
          <div><h3>Datasets</h3>
            ${(a.datasets || []).length
              ? `<div class="chips">${a.datasets.map((d) => `<span class="tag">${esc(d)}</span>`).join("")}</div>`
              : '<p class="muted">None named in the available text.</p>'}
            <div class="small muted" style="margin-top:6px">Extracted from the ${esc(a.datasets_source || "abstract")}.</div>
          </div>
          <div><h3>Venue</h3>
            <dl class="kv">
              <dt>Tier</dt><dd>${tierBadge(v.tier)} ${esc(TIER_INFO[v.tier] || "")}</dd>
              <dt>Venue</dt><dd>${esc(v.label)}${v.venue_type ? ` <span class="muted">(${esc(v.venue_type)})</span>` : ""}</dd>
              ${ranks ? `<dt>Rankings</dt><dd>${esc(ranks)}</dd>` : ""}
              <dt>Status</dt><dd>${esc(v.status)}${v.confidence === "inferred" ? ' <span class="muted">(inferred)</span>' : ""}</dd>
              ${v.evidence ? `<dt>Evidence</dt><dd class="muted">“${esc(v.evidence)}”</dd>` : ""}
              ${v.note ? `<dt>Note</dt><dd class="muted">${esc(v.note)}</dd>` : ""}
            </dl>
          </div>
          <div><h3>Relevance to track</h3>
            <div><span class="meter">${[1, 2, 3, 4, 5].map((i) => `<i class="${i <= rel ? "on" : ""}"></i>`).join("")}</span>${rel}/5</div>
            ${a.relevance_reason ? `<div class="small muted" style="margin-top:4px">${esc(a.relevance_reason)}</div>` : ""}
            ${(p.matched_keywords || []).length ? `<div class="chips" style="margin-top:8px">${p.matched_keywords.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</div>` : ""}
          </div>
        </div>
        <details class="abstract"><summary><b>Abstract</b></summary><p style="margin-top:8px">${esc(p.abstract)}</p>
          ${p.comment ? `<p class="small muted" style="margin-top:8px">Author comment: ${esc(p.comment)}</p>` : ""}
          <p class="small muted" style="margin-top:8px">Report engine: ${esc(a.engine || "—")}</p>
        </details>
      </div>`;
  }

  function rerenderPaper(id) {
    const p = state.papers.find((x) => x.id === id);
    const el = $(`article.paper[data-id="${CSS.escape(id)}"]`);
    if (p && el) el.outerHTML = paperCard(p);
    updateChrome();
  }

  function bindPapers() {
    const f = state.ui.papers;
    const q = $("#pf-q");
    if (!q) return;
    let timer;
    q.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(() => { f.q = q.value; f.limit = 40; rerender({ keepFocus: "#pf-q" }); }, 160);
    });
    $("#pf-track").addEventListener("change", (e) => { f.track = e.target.value; f.limit = 40; rerender(); });
    $("#pf-range").addEventListener("change", (e) => { f.range = e.target.value; f.limit = 40; rerender(); });
    $("#pf-sort").addEventListener("change", (e) => { f.sort = e.target.value; rerender(); });
  }

  // ------------------------------------------------------------------------ //
  // Live search (OpenAlex)
  // ------------------------------------------------------------------------ //
  function reconstructAbstract(inv) {
    if (!inv) return "";
    const slots = [];
    for (const [word, positions] of Object.entries(inv)) for (const i of positions) slots[i] = word;
    return slots.filter((w) => w !== undefined).join(" ");
  }

  function openalexToPaper(w) {
    const loc = w.primary_location || {};
    const src = loc.source || {};
    const venue = state.resolver
      ? state.resolver.fromSourceName(src.display_name, src.type)
      : { label: src.display_name || "Unknown venue", tier: "NR", status: "published" };
    const doi = (w.doi || "").replace("https://doi.org/", "") || null;
    return {
      id: "openalex:" + String(w.id).split("/").pop(),
      title: w.title || w.display_name || "(untitled)",
      authors: (w.authorships || []).map((a) => (a.author || {}).display_name).filter(Boolean),
      abstract: reconstructAbstract(w.abstract_inverted_index),
      published: w.publication_date,
      cited_by_count: w.cited_by_count || 0,
      url: loc.landing_page_url || w.doi || w.id,
      pdf_url: loc.pdf_url || (w.open_access || {}).oa_url || null,
      doi,
      arxiv_id: doi && doi.toLowerCase().startsWith("10.48550/arxiv.") ? doi.split(/arxiv\./i)[1] : null,
      venue,
      source: "openalex",
    };
  }

  async function runSearch(append) {
    const s = state.ui.search;
    if (!s.q.trim()) return;
    s.loading = true; s.error = null;
    if (!append) { s.page = 1; s.results = []; }
    rerender();
    const filters = ["has_abstract:true"];
    if (s.from) filters.push(`from_publication_date:${s.from}`);
    if (s.to) filters.push(`to_publication_date:${s.to}`);
    if (s.type !== "any") filters.push(`primary_location.source.type:${s.type}`);
    if (s.oa) filters.push("open_access.is_oa:true");
    const params = new URLSearchParams({
      search: s.q.trim(),
      filter: filters.join(","),
      "per-page": "50",
      page: String(s.page),
      select: "id,doi,title,display_name,publication_date,authorships,primary_location,abstract_inverted_index,cited_by_count,open_access",
    });
    if (s.sort === "newest") params.set("sort", "publication_date:desc");
    if (s.sort === "cited") params.set("sort", "cited_by_count:desc");
    if (state.settings.contact_email) params.set("mailto", state.settings.contact_email);
    try {
      const resp = await fetch("https://api.openalex.org/works?" + params.toString());
      if (!resp.ok) throw new Error(`OpenAlex returned ${resp.status}`);
      const data = await resp.json();
      s.count = (data.meta || {}).count || 0;
      s.results = s.results.concat((data.results || []).map(openalexToPaper));
    } catch (e) {
      s.error = e.message || String(e);
    }
    s.loading = false;
    rerender();
  }

  function renderSearch() {
    const s = state.ui.search;
    const minRank = { any: -1, T3: 3, T2: 4, T1: 5 }[s.minTier];
    const results = s.results.filter((p) => s.minTier === "any" || TIER_RANK[p.venue.tier] >= minRank && p.venue.tier !== "WS");
    const body = s.error
      ? `<div class="banner warn">Search failed: ${esc(s.error)}</div>`
      : !s.results.length && !s.loading
        ? `<div class="card empty"><h2>Search the literature</h2>
             <p>Queries run live against OpenAlex (journals, conferences and arXiv), and every result is
             tagged with the same venue tiers used by your tracks. Use quotes for phrases and
             <span class="code">OR</span> / <span class="code">AND</span> / <span class="code">NOT</span> for boolean logic.</p></div>`
        : `<div class="toolbar" style="justify-content:space-between">
             <span class="muted">${s.count.toLocaleString("en-US")} results · showing ${results.length} of ${s.results.length} loaded${s.minTier !== "any" ? ` (tier ≥ ${esc(s.minTier)})` : ""}</span>
             <button class="btn btn-sm" data-action="track-query">${ICON.plus} Track this query</button>
           </div>
           ${results.map(searchCard).join("")}
           ${s.loading ? '<div class="loading">Searching…</div>' : ""}
           ${s.results.length < s.count && !s.loading ? `<div class="more"><button class="btn" data-action="search-more">Load more</button></div>` : ""}`;
    return `
      ${pageHead("Search", "Detailed literature retrieval across journals, conferences and preprints")}
      <form class="card card-pad" id="search-form" style="margin-bottom:18px">
        <div class="form-grid">
          <div class="field full"><label for="sq">Query</label>
            <div class="search-box">${ICON.search}<input class="input" id="sq" type="search" required
              placeholder='e.g. "graph foundation model" OR "graph transformer"' value="${esc(s.q)}"></div></div>
          <div class="field"><label for="sfrom">Published from</label><input class="input" id="sfrom" type="date" value="${esc(s.from)}"></div>
          <div class="field"><label for="sto">Published to</label><input class="input" id="sto" type="date" value="${esc(s.to)}"></div>
          <div class="field"><label for="stype">Source type</label>
            <select class="select" id="stype">${[["any", "Any"], ["journal", "Journals"], ["conference", "Conferences"], ["repository", "Preprint servers"]]
              .map(([v, l]) => `<option value="${v}" ${s.type === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="field"><label for="stier">Minimum venue tier</label>
            <select class="select" id="stier">${[["any", "Any"], ["T1", "T1 · Top tier"], ["T2", "T2 · Strong or better"], ["T3", "T3 · Solid or better"]]
              .map(([v, l]) => `<option value="${v}" ${s.minTier === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="field"><label for="ssort">Sort by</label>
            <select class="select" id="ssort">${[["relevance", "Relevance"], ["newest", "Newest"], ["cited", "Most cited"]]
              .map(([v, l]) => `<option value="${v}" ${s.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="field" style="justify-content:flex-end"><label class="check"><input type="checkbox" id="soa" ${s.oa ? "checked" : ""}> Open access only</label></div>
        </div>
        <div style="display:flex;gap:8px;margin-top:16px">
          <button class="btn btn-primary" type="submit" ${s.loading ? "disabled" : ""}>${ICON.search} Search</button>
          <button class="btn" type="button" data-action="search-preset" data-days="30">Past 30 days</button>
          <button class="btn" type="button" data-action="search-preset" data-days="365">Past year</button>
        </div>
      </form>
      ${body}`;
  }

  function searchCard(p) {
    return `
      <article class="card paper is-read">
        <div class="paper-meta">${tierBadge(p.venue.tier)}<span class="venue">${esc(p.venue.label)}</span>
          ${p.published ? `<span class="dot">${esc(fmtDate(p.published))}</span>` : ""}
          <span class="dot">${esc(p.cited_by_count)} citations</span></div>
        <h3 class="paper-title"><a href="${safeUrl(p.url)}" target="_blank" rel="noopener">${esc(p.title)}</a></h3>
        <div class="paper-authors">${authorsLine(p.authors)}</div>
        ${p.abstract ? `<details><summary class="small muted" style="cursor:pointer">Abstract</summary>
          <p style="margin:8px 0 0;color:var(--text-2)">${esc(p.abstract)}</p></details>` : ""}
        <div class="paper-actions" style="margin-top:8px">
          ${p.pdf_url ? `<a class="btn btn-ghost" href="${safeUrl(p.pdf_url)}" target="_blank" rel="noopener">${ICON.doc} PDF</a>` : ""}
          <a class="btn btn-ghost" href="${safeUrl(p.url)}" target="_blank" rel="noopener">${ICON.ext} Source</a>
          <button class="btn btn-ghost" data-action="cite-search" data-id="${esc(p.id)}">${ICON.quote} Cite</button>
        </div>
      </article>`;
  }

  function bindSearch() {
    const form = $("#search-form");
    if (!form) return;
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const s = state.ui.search;
      s.q = $("#sq").value; s.from = $("#sfrom").value; s.to = $("#sto").value;
      s.type = $("#stype").value; s.sort = $("#ssort").value; s.oa = $("#soa").checked;
      s.minTier = $("#stier").value;
      runSearch(false);
    });
    $("#stier").addEventListener("change", (e) => { state.ui.search.minTier = e.target.value; rerender(); });
  }

  // ------------------------------------------------------------------------ //
  // News
  // ------------------------------------------------------------------------ //
  async function loadIssue(id) {
    if (!state.issues[id]) state.issues[id] = await getJSON(`data/news/issues/${encodeURIComponent(id)}.json`);
    return state.issues[id];
  }

  function renderNewsShell() {
    if (!state.newsIndex.issues.length) {
      return `${pageHead("News", "Research-community briefings")}
        <div class="card empty"><h2>No briefings yet</h2>
          <p>A briefing is compiled from ${esc(((state.settings.news || {}).cadence_days) || 3)}-day windows of
          journal news, lab blogs and community sources, and pushed to your channels. The first one appears after the next scheduled run.</p></div>`;
    }
    return `<div id="news-root"><div class="loading">Loading briefing…</div></div>`;
  }

  async function hydrateNews(id) {
    const root = $("#news-root");
    if (!root) return;
    const entry = id ? state.newsIndex.issues.find((i) => i.id === id) : state.newsIndex.issues[0];
    if (!entry) { root.innerHTML = `<div class="card empty"><h2>Issue not found</h2></div>`; return; }
    const issue = await loadIssue(entry.id);
    if (!issue) { root.innerHTML = `<div class="card empty"><h2>Could not load this issue</h2></div>`; return; }
    if (!$("#news-root")) return; // navigated away meanwhile
    const items = Object.fromEntries(issue.items.map((it) => [it.id, it]));
    const cat = state.ui.newsCategory;
    const cats = Array.from(new Set(issue.items.map((i) => i.category)));
    const shownItems = issue.items.filter((i) => cat === "all" || i.category === cat);
    const srcLink = (iid) => items[iid]
      ? `<a class="src" href="${safeUrl(items[iid].link)}" target="_blank" rel="noopener" title="${esc(items[iid].title)}">${esc(items[iid].source_name)}</a>` : "";
    const engine = issue.engine === "heuristic"
      ? '<div class="banner warn">This issue was compiled without the LLM (no API key), so it lists headlines rather than an edited synthesis.</div>' : "";

    root.innerHTML = `
      ${pageHead("News", `Issue of ${fmtDate(issue.generated_at, { month: "long", day: "numeric", year: "numeric" })}`,
        `<a class="btn btn-sm" href="feeds/news.xml">${ICON.feed} Atom feed</a>`)}
      <div class="issue-layout">
        <div class="stack">
          <article class="card brief">
            ${engine}
            <div class="period">${esc(fmtDate(issue.period_start))} – ${esc(fmtDate(issue.period_end))} · ${issue.items.length} items</div>
            <h1>${esc(issue.headline)}</h1>
            <p class="overview">${esc(issue.overview)}</p>
            ${(issue.top_picks || []).length ? `<h2>Top picks</h2><div class="picks">${issue.top_picks.filter((i) => items[i]).map((i) => `
              <a class="pick" href="${safeUrl(items[i].link)}" target="_blank" rel="noopener">
                <div class="s">${esc(items[i].source_name)}</div><div class="t">${esc(items[i].title)}</div></a>`).join("")}</div>` : ""}
            ${(issue.sections || []).map((s) => `<h2>${esc(s.theme)}</h2>
              <ul>${s.points.map((pt) => `<li>${esc(pt.text)} ${pt.item_ids.map(srcLink).join("")}</li>`).join("")}</ul>`).join("")}
          </article>
          <section class="card">
            <div class="card-head"><h2>All items</h2>
              <div class="chips">${["all"].concat(cats).map((c) => `<button class="chip" data-action="news-cat" data-cat="${esc(c)}" aria-pressed="${cat === c}">${esc(c === "all" ? "All" : c)}</button>`).join("")}</div>
            </div>
            <div class="card-pad" style="padding-top:4px;padding-bottom:4px">
              ${shownItems.map((it) => `<div class="news-item">
                <a class="t" href="${safeUrl(it.link)}" target="_blank" rel="noopener">${esc(it.title)}</a>
                ${it.summary ? `<div class="s">${esc(it.summary.length > 280 ? it.summary.slice(0, 280) + "…" : it.summary)}</div>` : ""}
                <div class="m">${esc(it.source_name)} · ${esc(it.category)}${it.published ? ` · ${esc(fmtDate(it.published))}` : ""}</div></div>`).join("")}
            </div>
          </section>
        </div>
        <aside class="stack">
          <section class="card"><div class="card-head"><h2>Archive</h2></div>
            <nav class="issue-list">${state.newsIndex.issues.slice(0, 30).map((i) => `
              <a href="#/news/${esc(i.id)}" class="${i.id === issue.id ? "active" : ""}">
                <div class="d">${esc(fmtDate(i.generated_at))} · ${esc(i.item_count)} items</div>
                <div class="h">${esc(i.headline)}</div></a>`).join("")}</nav>
          </section>
          <section class="card"><div class="card-head"><h2>Sources</h2></div>
            <div class="card-pad small">${(issue.sources || []).map((s) => `
              <div style="display:flex;justify-content:space-between;gap:8px;padding:3px 0" title="${esc(s.error || "")}">
                <span><i class="${s.ok ? "dot-ok" : "dot-bad"}"></i>${esc(s.name)}</span>
                <span class="muted">${s.ok ? esc(s.count) : "failed"}</span></div>`).join("")}</div>
          </section>
        </aside>
      </div>`;
  }

  // ------------------------------------------------------------------------ //
  // Tracks (editable; saved to GitHub when connected)
  // ------------------------------------------------------------------------ //
  const GH_API = "https://api.github.com";

  async function gh(path, options) {
    const g = state.github;
    if (!g || !g.token) throw new Error("GitHub is not connected (see Settings).");
    const resp = await fetch(GH_API + path, Object.assign({}, options, {
      headers: Object.assign({
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${g.token}`,
        "X-GitHub-Api-Version": "2022-11-28",
      }, (options || {}).headers || {}),
    }));
    if (!resp.ok) {
      let msg = resp.statusText;
      try { msg = (await resp.json()).message || msg; } catch (e) { /* no body */ }
      throw new Error(`GitHub ${resp.status}: ${msg}`);
    }
    return resp.status === 204 ? null : resp.json();
  }

  function b64encode(text) {
    const bytes = new TextEncoder().encode(text);
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(bin);
  }
  const b64decode = (b64) =>
    new TextDecoder().decode(Uint8Array.from(atob(b64.replace(/\s/g, "")), (c) => c.charCodeAt(0)));

  const repoPath = () => `/repos/${encodeURIComponent(state.github.owner)}/${encodeURIComponent(state.github.repo)}`;

  async function pullTracksFromGitHub() {
    if (!state.github || !state.github.token || state.tracksDirty) return;
    try {
      const file = await gh(`${repoPath()}/contents/config/tracks.json?ref=${encodeURIComponent(state.github.branch || "main")}`);
      state.tracks = JSON.parse(b64decode(file.content)).tracks || [];
      state.tracksSha = file.sha;
    } catch (e) {
      toast(`Could not read tracks from GitHub: ${e.message}`);
    }
  }

  async function saveTracks() {
    const json = JSON.stringify({ tracks: state.tracks }, null, 2) + "\n";
    if (!state.github || !state.github.token) {
      state.tracksDirty = true;
      rerender();
      toast("Changes kept locally. Download tracks.json or connect GitHub to save.");
      return;
    }
    try {
      if (!state.tracksSha) {
        const file = await gh(`${repoPath()}/contents/config/tracks.json?ref=${encodeURIComponent(state.github.branch || "main")}`);
        state.tracksSha = file.sha;
      }
      const res = await gh(`${repoPath()}/contents/config/tracks.json`, {
        method: "PUT",
        body: JSON.stringify({
          message: "Update research tracks from the console",
          content: b64encode(json),
          sha: state.tracksSha,
          branch: state.github.branch || "main",
        }),
      });
      state.tracksSha = res.content.sha;
      state.tracksDirty = false;
      rerender();
      toast("Saved to GitHub. New tracks take effect on the next run.");
    } catch (e) {
      state.tracksDirty = true;
      rerender();
      toast(`Save failed: ${e.message}`);
    }
  }

  async function dispatchRun(job, forceNews) {
    try {
      await gh(`${repoPath()}/actions/workflows/update.yml/dispatches`, {
        method: "POST",
        body: JSON.stringify({ ref: state.github.branch || "main",
                               inputs: { job: job || "all", force_news: forceNews ? "true" : "false" } }),
      });
      toast("Workflow started. Results appear here in a few minutes.");
    } catch (e) {
      toast(`Could not start the workflow: ${e.message}`);
    }
  }

  function renderTracks() {
    const connected = !!(state.github && state.github.token);
    const stats = Object.fromEntries(((state.meta.papers || {}).tracks || []).map((t) => [t.track_id, t]));
    const actions = `
      <button class="btn btn-sm" data-action="run-now" ${connected ? "" : "disabled title='Connect GitHub in Settings'"}>${ICON.play} Run now</button>
      <button class="btn btn-sm" data-action="export-tracks">${ICON.download} Export JSON</button>
      <button class="btn btn-sm btn-primary" data-action="new-track">${ICON.plus} New track</button>`;
    const banner = state.tracksDirty
      ? `<div class="banner warn">You have unsaved track changes.&nbsp;<a href="#" data-action="export-tracks">Download tracks.json</a>&nbsp;and commit it to <span class="code">config/</span>, or connect GitHub in <a href="#/settings">Settings</a>.</div>`
      : !connected
        ? `<div class="banner">Tracks are read from <span class="code">config/tracks.json</span>. Connect GitHub in <a href="#/settings">Settings</a> to save edits and trigger runs from here.</div>`
        : "";
    const cards = state.tracks.map((t, i) => {
      const s = stats[t.id];
      return `
        <article class="card track">
          <div class="track-head">
            <div><h2>${esc(t.name)} ${t.enabled === false ? '<span class="badge-off">Paused</span>' : ""}</h2>
              ${t.description ? `<p>${esc(t.description)}</p>` : ""}</div>
            <div style="display:flex;gap:4px">
              <button class="icon-btn" data-action="edit-track" data-index="${i}" aria-label="Edit ${esc(t.name)}" title="Edit">${ICON.edit}</button>
              <button class="icon-btn" data-action="dup-track" data-index="${i}" aria-label="Duplicate ${esc(t.name)}" title="Duplicate">${ICON.copy}</button>
              <button class="icon-btn" data-action="del-track" data-index="${i}" aria-label="Delete ${esc(t.name)}" title="Delete">${ICON.trash}</button>
            </div>
          </div>
          <dl class="track-body">
            <dt>Keywords</dt><dd>${(t.keywords || []).map((k) => `<span class="tag tag-accent">${esc(k)}</span>`).join("")}</dd>
            ${(t.exclude || []).length ? `<dt>Excluding</dt><dd>${t.exclude.map((k) => `<span class="tag">${esc(k)}</span>`).join("")}</dd>` : ""}
            <dt>arXiv</dt><dd>${(t.arxiv_categories || []).map((k) => `<span class="tag mono">${esc(k)}</span>`).join("") || '<span class="muted">any category</span>'}</dd>
            <dt>Quality bar</dt><dd><span class="muted">Published venues ≥ ${esc(t.min_tier === "any" ? "any tier" : t.min_tier)} · preprints ${t.include_preprints ? "included" : "excluded"} · sources: ${esc((t.sources || []).join(", "))}</span></dd>
            <dt>Window</dt><dd><span class="muted">Last ${esc(t.lookback_days)} days · up to ${esc(t.max_papers)} papers per run</span></dd>
          </dl>
          ${s ? `<div class="track-stats"><span>Last run: <b>${esc(s.fetched)}</b> fetched</span><span><b>${esc(s.candidates)}</b> new candidates</span><span><b>${esc(s.selected)}</b> reported</span>
            ${(s.errors || []).length ? `<span class="note" title="${esc(s.errors.join("\n"))}">${s.errors.length} source error(s)</span>` : ""}</div>` : ""}
        </article>`;
    }).join("");
    return `${pageHead("Tracks", "Research fields the pipeline monitors daily", actions)}
      ${banner}
      <div class="stack">${cards || '<div class="card empty"><h2>No tracks yet</h2><p>Create one to start receiving papers.</p></div>'}</div>`;
  }

  const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 40) || "track";
  const listFromText = (s) => String(s || "").split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

  function openTrackEditor(index, prefill) {
    const isNew = index === null || index === undefined;
    const t = isNew
      ? Object.assign({ id: "", name: "", description: "", enabled: true, keywords: [], exclude: [],
          arxiv_categories: ["cs.LG"], sources: ["arxiv", "openalex"], include_preprints: true,
          min_tier: "T2", lookback_days: 3, max_papers: 8 }, prefill || {})
      : state.tracks[index];
    const wrap = document.createElement("div");
    wrap.className = "modal-backdrop";
    wrap.innerHTML = `
      <form class="card modal" role="dialog" aria-modal="true" aria-labelledby="te-title">
        <div class="card-head"><h2 id="te-title">${isNew ? "New track" : "Edit track"}</h2>
          <button type="button" class="icon-btn" data-close aria-label="Close">✕</button></div>
        <div class="card-pad form-grid">
          <div class="field"><label for="te-name">Name</label><input class="input" id="te-name" required value="${esc(t.name)}"></div>
          <div class="field"><label for="te-id">ID</label><input class="input mono" id="te-id" value="${esc(t.id)}" placeholder="auto from name" ${isNew ? "" : "readonly"}>
            <span class="hint">${isNew ? "Lowercase slug; cannot be changed later." : "IDs are permanent so archived papers stay linked."}</span></div>
          <div class="field full"><label for="te-desc">Description</label><input class="input" id="te-desc" value="${esc(t.description || "")}"></div>
          <div class="field full"><label for="te-kw">Keywords</label>
            <textarea class="textarea" id="te-kw" rows="4" required>${esc((t.keywords || []).join("\n"))}</textarea>
            <span class="hint">One per line. A paper must contain at least one in its title or abstract (hyphen/space and plural variants match). Specific phrases beat broad terms.</span></div>
          <div class="field"><label for="te-ex">Exclude terms</label><textarea class="textarea" id="te-ex" rows="2">${esc((t.exclude || []).join("\n"))}</textarea></div>
          <div class="field"><label for="te-cat">arXiv categories</label><textarea class="textarea mono" id="te-cat" rows="2">${esc((t.arxiv_categories || []).join("\n"))}</textarea>
            <span class="hint">e.g. cs.LG, cs.CL, stat.ML. Empty = all.</span></div>
          <div class="field"><label for="te-tier">Minimum tier for published papers</label>
            <select class="select" id="te-tier">${[["T1", "T1 · Top tier"], ["T2", "T2 · Strong or better"], ["T3", "T3 · Solid or better"], ["any", "Any venue"]]
              .map(([v, l]) => `<option value="${v}" ${t.min_tier === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
          <div class="field"><label>Sources</label>
            <div style="display:flex;gap:16px;align-items:center;height:34px">
              <label class="check"><input type="checkbox" id="te-arxiv" ${(t.sources || []).includes("arxiv") ? "checked" : ""}> arXiv</label>
              <label class="check"><input type="checkbox" id="te-oa" ${(t.sources || []).includes("openalex") ? "checked" : ""}> OpenAlex</label>
            </div></div>
          <div class="field"><label for="te-look">Lookback (days)</label><input class="input" id="te-look" type="number" min="1" max="30" value="${esc(t.lookback_days)}"></div>
          <div class="field"><label for="te-max">Max papers per run</label><input class="input" id="te-max" type="number" min="1" max="50" value="${esc(t.max_papers)}"></div>
          <div class="field full" style="flex-direction:row;gap:22px;flex-wrap:wrap">
            <label class="check"><input type="checkbox" id="te-pre" ${t.include_preprints ? "checked" : ""}> Include arXiv preprints</label>
            <label class="check"><input type="checkbox" id="te-on" ${t.enabled !== false ? "checked" : ""}> Enabled</label>
          </div>
          <p class="note full" id="te-err" hidden></p>
        </div>
        <div class="modal-foot">
          <button type="button" class="btn" data-close>Cancel</button>
          <button type="submit" class="btn btn-primary">${state.github && state.github.token ? "Save to GitHub" : "Save"}</button>
        </div>
      </form>`;
    document.body.appendChild(wrap);
    const form = $("form", wrap);
    const close = () => wrap.remove();
    $$("[data-close]", wrap).forEach((b) => b.addEventListener("click", close));
    wrap.addEventListener("click", (e) => { if (e.target === wrap) close(); });
    wrap.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    $("#te-name", wrap).focus();

    form.addEventListener("submit", (e) => {
      e.preventDefault();
      const err = $("#te-err", wrap);
      const name = $("#te-name", wrap).value.trim();
      const id = isNew ? slug($("#te-id", wrap).value.trim() || name) : t.id;
      const track = {
        id, name,
        description: $("#te-desc", wrap).value.trim(),
        enabled: $("#te-on", wrap).checked,
        keywords: listFromText($("#te-kw", wrap).value),
        exclude: listFromText($("#te-ex", wrap).value),
        arxiv_categories: listFromText($("#te-cat", wrap).value),
        sources: [$("#te-arxiv", wrap).checked ? "arxiv" : null, $("#te-oa", wrap).checked ? "openalex" : null].filter(Boolean),
        include_preprints: $("#te-pre", wrap).checked,
        min_tier: $("#te-tier", wrap).value,
        lookback_days: Math.max(1, Math.min(30, parseInt($("#te-look", wrap).value, 10) || 3)),
        max_papers: Math.max(1, Math.min(50, parseInt($("#te-max", wrap).value, 10) || 8)),
      };
      const problems = [];
      if (!name) problems.push("Name is required.");
      if (!track.keywords.length) problems.push("Add at least one keyword.");
      if (!track.sources.length) problems.push("Select at least one source.");
      if (isNew && state.tracks.some((x) => x.id === id)) problems.push(`A track with id "${id}" already exists.`);
      if (problems.length) { err.hidden = false; err.textContent = problems.join(" "); return; }
      if (isNew) state.tracks.push(track); else state.tracks[index] = track;
      close();
      saveTracks();
    });
  }

  // ------------------------------------------------------------------------ //
  // Settings
  // ------------------------------------------------------------------------ //
  function guessRepo() {
    const host = location.hostname;
    if (host.endsWith(".github.io")) {
      return { owner: host.replace(".github.io", ""), repo: location.pathname.split("/").filter(Boolean)[0] || "" };
    }
    return { owner: "", repo: "" };
  }

  function renderSettings() {
    const g = state.github || Object.assign({ branch: "main", token: "" }, guessRepo());
    const ch = state.meta.channels || {};
    const site = (state.settings.site_url || "").replace(/\/?$/, "/");
    const theme = store.get("rc.theme", "system");
    const channelRow = (name, label, secrets) => `
      <div style="display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--border)">
        <div><b>${label}</b><div class="small muted">Secrets: ${secrets.map((s) => `<span class="code">${s}</span>`).join(" ")}</div></div>
        <div class="small" style="white-space:nowrap"><i class="${ch[name] ? "dot-ok" : "dot-off"}"></i>${ch[name] ? "Active" : "Not configured"}</div>
      </div>`;
    return `${pageHead("Settings")}
      <div class="grid grid-2">
        <div class="stack">
          <section class="card">
            <div class="card-head"><h2>GitHub connection</h2>${g.token ? '<span class="small"><i class="dot-ok"></i>Connected</span>' : ""}</div>
            <form class="card-pad" id="gh-form">
              <div class="form-grid">
                <div class="field"><label for="gh-owner">Owner</label><input class="input" id="gh-owner" value="${esc(g.owner)}" required></div>
                <div class="field"><label for="gh-repo">Repository</label><input class="input" id="gh-repo" value="${esc(g.repo)}" required></div>
                <div class="field"><label for="gh-branch">Branch</label><input class="input" id="gh-branch" value="${esc(g.branch || "main")}"></div>
                <div class="field"><label for="gh-token">Fine-grained token</label><input class="input mono" id="gh-token" type="password" autocomplete="off" value="${esc(g.token)}" placeholder="github_pat_…"></div>
              </div>
              <p class="small muted" style="margin:12px 0 0">Create a fine-grained personal access token limited to this repository with
                <b>Contents: read &amp; write</b> and <b>Actions: read &amp; write</b>. It is stored only in this browser's local storage and sent only to api.github.com.</p>
              <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
                <button class="btn btn-primary" type="submit">Save &amp; test</button>
                ${g.token ? '<button class="btn btn-danger" type="button" data-action="gh-disconnect">Disconnect</button>' : ""}
              </div>
            </form>
          </section>
          <section class="card">
            <div class="card-head"><h2>Push notifications</h2></div>
            <div class="card-pad" style="padding-top:4px">
              ${channelRow("email", "Email", ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"])}
              ${channelRow("telegram", "Telegram", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"])}
              ${channelRow("ntfy", "ntfy (phone push)", ["NTFY_TOPIC"])}
              <p class="small muted" style="margin:12px 0 0">Add secrets under <i>Repository → Settings → Secrets and variables → Actions</i>. Status reflects the most recent run.</p>
            </div>
          </section>
        </div>
        <div class="stack">
          <section class="card">
            <div class="card-head"><h2>Feeds</h2></div>
            <div class="card-pad stack" style="gap:10px">
              ${[["Papers", "feeds/papers.xml"], ["Briefings", "feeds/news.xml"]].map(([l, p]) => `
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
                  <span>${ICON.feed.replace("<svg", '<svg width="15" height="15" style="fill:none;stroke:currentColor;stroke-width:1.8;vertical-align:-2px"')} ${l}</span>
                  <button class="btn btn-sm" data-action="copy" data-text="${esc(site + p)}">${ICON.copy} Copy URL</button></div>`).join("")}
              <p class="small muted" style="margin:0">Subscribe in any feed reader as an extra delivery channel.</p>
            </div>
          </section>
          <section class="card">
            <div class="card-head"><h2>Analysis engine</h2></div>
            <div class="card-pad"><dl class="status-rows">
              <dt>Current</dt><dd>${esc(engineLabel())}</dd>
              <dt>Model</dt><dd class="mono">${esc((state.settings.llm || {}).model || "—")}</dd>
              <dt>Effort</dt><dd>${esc((state.settings.llm || {}).effort || "—")}</dd>
            </dl><p class="small muted" style="margin:12px 0 0">Configured in <span class="code">config/settings.json</span>; requires the <span class="code">ANTHROPIC_API_KEY</span> secret.</p></div>
          </section>
          <section class="card">
            <div class="card-head"><h2>Appearance &amp; local data</h2></div>
            <div class="card-pad stack" style="gap:12px">
              <div class="field"><label for="set-theme">Theme</label>
                <select class="select" id="set-theme">${[["system", "System"], ["light", "Light"], ["dark", "Dark"]]
                  .map(([v, l]) => `<option value="${v}" ${theme === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>
              <div class="small muted">${state.read.size} papers marked read · ${state.starred.size} starred (stored in this browser)</div>
              <div style="display:flex;gap:8px;flex-wrap:wrap">
                <button class="btn btn-sm" data-action="export-starred" ${state.starred.size ? "" : "disabled"}>${ICON.download} Starred as BibTeX</button>
                <button class="btn btn-sm btn-danger" data-action="clear-read">Clear read marks</button>
              </div>
            </div>
          </section>
        </div>
      </div>`;
  }

  function bindSettings() {
    const form = $("#gh-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      state.github = {
        owner: $("#gh-owner").value.trim(), repo: $("#gh-repo").value.trim(),
        branch: $("#gh-branch").value.trim() || "main", token: $("#gh-token").value.trim(),
      };
      store.set("rc.github", state.github);
      try {
        const repo = await gh(repoPath());
        const perms = repo.permissions || {};
        toast(perms.push ? `Connected to ${repo.full_name}.` : `Connected, but the token cannot write to ${repo.full_name}.`);
        state.tracksSha = null;
        await pullTracksFromGitHub();
      } catch (err) {
        toast(err.message);
      }
      rerender();
    });
    $("#set-theme").addEventListener("change", (e) => setTheme(e.target.value));
  }

  function setTheme(value) {
    if (value === "system") { delete document.documentElement.dataset.theme; store.remove("rc.theme"); }
    else { document.documentElement.dataset.theme = value; store.set("rc.theme", value); }
  }

  // ------------------------------------------------------------------------ //
  // Router & events
  // ------------------------------------------------------------------------ //
  function currentRoute() {
    const parts = location.hash.replace(/^#\/?/, "").split("/");
    return { name: parts[0] || "overview", arg: parts[1] ? decodeURIComponent(parts[1]) : null };
  }

  function rerender(opts) {
    const main = $("#main");
    const route = currentRoute();
    const focusSel = opts && opts.keepFocus;
    const caret = focusSel && $(focusSel) ? $(focusSel).selectionStart : null;
    const views = {
      overview: renderOverview, papers: renderPapers, search: renderSearch,
      news: renderNewsShell, tracks: renderTracks, settings: renderSettings,
    };
    main.innerHTML = (views[route.name] || renderOverview)();
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.route === (views[route.name] ? route.name : "overview")));
    if (route.name === "overview") hydrateOverview();
    if (route.name === "papers") bindPapers();
    if (route.name === "search") bindSearch();
    if (route.name === "news") hydrateNews(route.arg);
    if (route.name === "settings") bindSettings();
    if (focusSel && $(focusSel)) { const el = $(focusSel); el.focus(); if (caret !== null) el.setSelectionRange(caret, caret); }
    updateChrome();
  }

  function onClick(e) {
    const el = e.target.closest("[data-action]");
    if (!el) return;
    const action = el.dataset.action;
    const card = el.closest("article.paper[data-id]");
    const id = card ? card.dataset.id : el.dataset.id;
    const f = state.ui.papers;
    const paper = id ? state.papers.find((p) => p.id === id) : null;

    switch (action) {
      case "toggle-report":
        if (state.ui.expanded.has(id)) state.ui.expanded.delete(id);
        else { state.ui.expanded.add(id); state.read.add(id); saveRead(); }
        rerenderPaper(id); break;
      case "open-paper":
        state.read.add(id); saveRead(); setTimeout(() => rerenderPaper(id), 0); break;
      case "read":
        if (state.read.has(id)) state.read.delete(id); else state.read.add(id);
        saveRead(); rerenderPaper(id); break;
      case "star":
        if (state.starred.has(id)) state.starred.delete(id); else state.starred.add(id);
        saveStarred(); rerenderPaper(id); break;
      case "cite":
        if (paper) copyText(bibtex(paper), "BibTeX copied"); break;
      case "cite-search": {
        const p = state.ui.search.results.find((x) => x.id === id);
        if (p) copyText(bibtex(p), "BibTeX copied"); break;
      }
      case "focus-paper":
        e.preventDefault();
        state.ui.expanded.add(id);
        Object.assign(f, { q: "", track: "all", range: "all", unread: false, starred: false, limit: 400 });
        f.tiers = new Set(["T1", "T2", "T3", "WS", "PP", "NR"]);
        location.hash = "#/papers";
        setTimeout(() => { const t = $(`article.paper[data-id="${CSS.escape(id)}"]`); if (t) t.scrollIntoView({ block: "start" }); }, 30);
        break;
      case "mark-all-read":
        filteredPapers().slice(0, f.limit).forEach((p) => state.read.add(p.id));
        saveRead(); rerender(); break;
      case "tier":
        if (f.tiers.has(el.dataset.tier)) f.tiers.delete(el.dataset.tier); else f.tiers.add(el.dataset.tier);
        rerender(); break;
      case "toggle-unread": f.unread = !f.unread; rerender(); break;
      case "toggle-starred": f.starred = !f.starred; rerender(); break;
      case "more-papers": f.limit += 40; rerender(); break;
      case "search-more": state.ui.search.page += 1; runSearch(true); break;
      case "search-preset": {
        const d = new Date(Date.now() - Number(el.dataset.days) * 86400e3);
        $("#sfrom").value = d.toISOString().slice(0, 10);
        $("#sto").value = "";
        break;
      }
      case "track-query": {
        const kws = state.ui.search.q.split(/\s+OR\s+|,/i).map((s) => s.replace(/["()]/g, "").trim()).filter(Boolean);
        location.hash = "#/tracks";
        setTimeout(() => openTrackEditor(null, { name: kws[0] ? kws[0].replace(/\b\w/g, (c) => c.toUpperCase()) : "", keywords: kws }), 30);
        break;
      }
      case "news-cat":
        state.ui.newsCategory = el.dataset.cat; hydrateNews(currentRoute().arg); break;
      case "new-track": openTrackEditor(null); break;
      case "edit-track": openTrackEditor(Number(el.dataset.index)); break;
      case "dup-track": {
        const src = state.tracks[Number(el.dataset.index)];
        openTrackEditor(null, Object.assign({}, src, { id: "", name: src.name + " (copy)" }));
        break;
      }
      case "del-track": {
        const t = state.tracks[Number(el.dataset.index)];
        if (window.confirm(`Delete the track "${t.name}"? Archived papers are kept.`)) {
          state.tracks.splice(Number(el.dataset.index), 1);
          saveTracks();
        }
        break;
      }
      case "export-tracks":
        e.preventDefault();
        download("tracks.json", JSON.stringify({ tracks: state.tracks }, null, 2) + "\n"); break;
      case "run-now":
        if (window.confirm("Start the pipeline now? Papers run immediately; a news briefing is forced as well.")) dispatchRun("all", true);
        break;
      case "gh-disconnect":
        state.github = null; store.remove("rc.github"); state.tracksSha = null; rerender(); toast("Disconnected."); break;
      case "copy": copyText(el.dataset.text, "URL copied"); break;
      case "export-starred": {
        const bib = state.papers.filter((p) => state.starred.has(p.id)).map(bibtex).join("\n\n");
        download("starred.bib", bib + "\n", "text/x-bibtex"); break;
      }
      case "clear-read":
        if (window.confirm("Clear all read marks in this browser?")) { state.read.clear(); saveRead(); rerender(); }
        break;
      default: break;
    }
  }

  function toggleTheme() {
    const cur = document.documentElement.dataset.theme
      || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    setTheme(cur === "dark" ? "light" : "dark");
    if (currentRoute().name === "settings") rerender();
  }

  async function init() {
    document.addEventListener("click", onClick);
    $("#theme-toggle").addEventListener("click", toggleTheme);
    window.addEventListener("hashchange", () => { rerender(); $("#main").focus({ preventScroll: true }); window.scrollTo(0, 0); });
    await loadData();
    await pullTracksFromGitHub();
    rerender();
  }

  init();
})();
