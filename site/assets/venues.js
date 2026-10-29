/* Client-side port of console/venues.py `from_source_name`, used by live search.
 * Kept deliberately small: it only resolves *published* venue names. */
(function (global) {
  "use strict";

  const WORKSHOP = /\b(workshops?|extended abstracts?|companion|doctoral consortium|demo track)\b/i;
  const REPOSITORY = /\barxiv\b|biorxiv|medrxiv|ssrn|research square/i;
  const YEAR = /(?<!\d)(19|20)\d{2}(?!\d)/;

  function normalize(text) {
    return String(text || "").toLowerCase().replace(/&/g, " and ")
      .replace(/[^a-z0-9]+/g, " ").replace(/\s+/g, " ").trim();
  }

  function VenueResolver(table) {
    this.tiers = table.tiers;
    this.exact = new Map();
    this.aliases = [];
    for (const v of table.venues) {
      for (const name of v.exact || []) this.exact.set(normalize(name), v);
      for (const a of v.aliases || []) this.aliases.push([normalize(a), v]);
    }
    this.aliases.sort((a, b) => b[0].length - a[0].length);
  }

  VenueResolver.prototype.matchAlias = function (text) {
    const norm = " " + normalize(text) + " ";
    for (const [alias, venue] of this.aliases) {
      const needle = " " + alias + " ";
      let idx = norm.indexOf(needle);
      while (idx !== -1) {
        const tail = norm.slice(idx + needle.length);
        if (!(alias.split(" ").length >= 3 && tail.startsWith("and "))) return venue;
        idx = norm.indexOf(needle, idx + 1);
      }
    }
    return null;
  };

  VenueResolver.prototype.fromSourceName = function (name, sourceType) {
    if (!name) return { label: "Unknown venue", key: null, tier: "NR", status: "published" };
    if (sourceType === "repository" || REPOSITORY.test(name)) {
      return { label: name, key: null, tier: "PP", status: "preprint" };
    }
    const venue = this.exact.get(normalize(name)) || this.matchAlias(name);
    if (!venue) return { label: name, key: null, tier: "NR", status: "published" };
    if (WORKSHOP.test(name)) {
      return { label: venue.key + " Workshop", key: venue.key, tier: "WS", status: "workshop",
               ccf: venue.ccf, core: venue.core };
    }
    const year = name.match(YEAR);
    return {
      label: venue.key + (year ? " " + year[0] : ""), key: venue.key, tier: venue.tier,
      status: "published", ccf: venue.ccf, core: venue.core, venue_type: venue.type, note: venue.note || null,
    };
  };

  global.VenueResolver = VenueResolver;
  global.normalizeVenue = normalize;
})(window);
