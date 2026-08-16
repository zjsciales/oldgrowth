# PROJECT_SUMMARY.md — Canopy (Wilmington Lot Scout)

> Working title: **Canopy**. Rename freely — used here for readability.

## What this is

A personal rating app for two people — Zach and Andrea — to jointly find a
house in Wilmington, NC. Every new listing in the target zips gets pulled
in, enriched with real GIS/canopy/market data, and reduced to a feature
vector. Both of you rate listings (swipe Yes/No/Maybe, or forced-choice
pairwise comparisons) with optional tags explaining why. A learned
preference model — one per rater, never averaged — turns those judgments
into a ranking, and a weekly digest surfaces the current top picks, the
listings the model is least sure about, a wildcard, and a dedicated
"where you two disagree" section.

Nothing is ever hard-filtered out. Every listing is ranked; bad features
cost rank, they don't eliminate a listing from consideration.

> **Later pivot** (see `ARCHITECTURE.md`'s Purpose section): listings
> ingestion moved from the RentCast API (described in decisions 1-2 below)
> to Zillow saved-search/recommendation alert emails polled via IMAP.
> RentCast's rows/history stay in the database as permanent historical
> data (`source = 'rentcast'`); everything downstream of ingestion is
> unchanged. The decisions below are preserved as the historical record of
> why the *original* design looked the way it did, not a description of
> current ingestion behavior.

## Why

- Manually cross-referencing Regrid, New Hanover County GIS, and satellite
  imagery for every promising listing works, but is slow and easy to let
  slip during a busy week.
- Keyword search on Zillow/Trulia/Redfin can't express "backs to protected
  marsh" or "old growth canopy" — these are spatial/visual qualities, not
  listing-description keywords.
- **The first version of this tool used a hand-set rule-based filter**
  (minimum lot size, minimum canopy %, required adjacency flag) and it
  collapsed 1025 real Wilmington listings down to 2 candidates. The
  failure mode was structural, not a tuning mistake: a single canopy-%
  threshold can't express that the number you'd reject a listing at and
  the number that would delight you are genuinely different values, and
  a hard filter has no way to surface "almost, but not quite" listings
  worth a second look. A learned model that ranks instead of gates, and
  reads dealbreaker/delight thresholds off your actual tagged judgments,
  is the fix — see `SCORING_MODEL.md`.

## Who it's for

Two users — Zach and Andrea — personal use, not a product, no plans to
productize. Rater identities are `zach` / `andrea` throughout the schema
and API.

## Decisions made so far

1. **Listings data source: RentCast API** (free tier, 50 calls/month),
   chosen over ATTOM (sales-call-gated, no perpetual free tier) and
   unofficial Realtor.com scrapers (ToS risk, unstable). Direct MLS access
   ruled out for now — requires a sponsoring broker/agent relationship.
2. **Cadence: weekly, per target neighborhood** — sized to the RentCast
   free tier's call budget and matched to the stated tolerance for
   up-to-a-week delay in fresh listings. This is a deliberate design
   choice, not a placeholder to optimize away.
3. **GIS enrichment: New Hanover County's public ArcGIS REST API** for
   parcel geometry, boundary/perimeter classification (what actually
   touches the lot, not just "any hit within a buffer"), flood zone, and
   wetland overlays; NLCD for tree canopy % — all computed
   deterministically, never by the model or the AI step.
4. **AI's role kept deliberately narrow**: a lazy, per-listing vision pass
   (on first view, not a bulk weekly step) extracts structural/
   architecture features — style, exterior material, garage type — and
   writes a plain-English rationale. It never scores, ranks, filters, or
   votes on preference; only rater judgments are training labels for the
   preference model (`SCORING_MODEL.md` §10).
5. **Every listing gets a full feature vector; nothing is hard-filtered.**
   Two people rate independently — swipes and pairwise comparisons — and a
   pairwise preference model is fit **separately per rater**, never
   averaged. The weekly digest combines both raters' scores as
   `min(z_a, z_b)`, not a mean, because a listing one of you loves and the
   other hates is not a good listing.
6. **Platform: Python/Flask + Postgres, React (Vite) for the rating UI.**
   Currently developed and run entirely locally (Docker Compose Postgres,
   local Flask serving the built frontend, macOS `launchd` for the weekly
   cron) — a move to Railway, matching the original v1 design, is planned
   next, once a production database is provisioned there.

## Non-goals

- Not scraping Zillow/Redfin/Realtor.com directly.
- Not pursuing broker-sponsored MLS access yet.
- Not real-time — weekly cadence is a deliberate design choice.
- Not eliminating listings via a hard filter, ever — the whole pivot exists
  because that failed once already.
- Not averaging the two raters' judgments into a single model.
- Not letting the AI vote on preference — it explains and extracts
  structure; your judgments are the only labels.

## Roadmap

**v1 (rule-based filter)** — superseded by the pivot below, but the
underlying data pipeline (ingest, GIS enrichment, canopy scoring) is
unchanged and still in use:

| Phase | Scope |
|---|---|
| 1 | Ingestion + storage — RentCast client, Postgres schema, dedupe logic |
| 2 | GIS enrichment — county ArcGIS parcel/adjacency lookup, flood/wetland flags |
| 3 | Canopy scoring — raster clip + % cover calc, old-growth proxy heuristic |
| ~~4~~ | ~~Rule-based filter~~ — retired; collapsed 1025 listings to 2, see "Why" above |
| ~~5~~ | ~~Claude sub-agent on the filtered shortlist~~ — retired; vision is now lazy, per-listing |
| 6 | Digest delivery — retained, rebuilt around the learned ranking |
| 7 | Deploy — retained as a goal, currently local-first (see decision 6 above) |

**v2 (rating & preference-learning pivot)** — see `FEATURE_SCHEMA.md`,
`SCORING_MODEL.md`, `UI_SPEC.md` for full design:

| Stage | Scope | Status |
|---|---|---|
| 1 | Preference-layer schema — features, tags, judgments, comparisons, anchors, model runs | Done |
| 2 | Feature vector computation — full `FEATURE_SCHEMA.md` vector, lazy vision pass | Done |
| 3 | Rating capture backend + JSON API | Done |
| 4 | Pairwise preference model (numpy/scipy, no scikit-learn) | Done |
| 5 | React rating UI (Vite), wired to the real API | Done |
| 6 | Cutover — retire the hard filter, wire the model into the weekly digest | Done |
| 7 | Docs reorganization (this pass) | In progress |
| — | Deferred: OpenStreetMap road/position features, real drive-time routing (currently a haversine proxy) | Not started |
| — | Railway redeploy | Not started |

## Reference

See `ARCHITECTURE.md` for full technical detail on each component
(including Known Limitations for risks found along the way), and
`FEATURE_SCHEMA.md`/`SCORING_MODEL.md`/`UI_SPEC.md` for the preference
layer's design.
