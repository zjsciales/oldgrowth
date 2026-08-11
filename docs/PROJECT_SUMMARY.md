# PROJECT_SUMMARY.md — Canopy (Wilmington Lot Scout)

> Working title: **Canopy**. Rename freely — used here for readability.

## What this is

A personal automation that scans new Wilmington, NC real estate listings on
a weekly cadence and surfaces the handful whose *lots* match specific
criteria: backing to water, a park, or unbuildable marsh; large and heavily
wooded; located in an old-growth tree canopy neighborhood. Delivers a
scored, short-listed digest rather than requiring manual searching.

## Why

- Manually cross-referencing Regrid, New Hanover County GIS, and satellite
  imagery for every promising listing works, but is slow and easy to let
  slip during a busy week.
- Keyword search on Zillow/Trulia/Redfin can't express "backs to protected
  marsh" or "old growth canopy" — these are spatial/visual qualities, not
  listing-description keywords.
- Goal: an automated recurring shortlist instead of a manual weekly check.

## Who it's for

Single user (Zach), personal use — not a product, no plans to productize.

## Decisions made so far

1. **Listings data source: RentCast API** (free tier, 50 calls/month),
   chosen over ATTOM (sales-call-gated, no perpetual free tier) and
   unofficial Realtor.com scrapers (ToS risk, unstable). Direct MLS access
   ruled out for now — requires a sponsoring broker/agent relationship.
2. **Cadence: weekly, per target neighborhood** — sized to the RentCast free
   tier's call budget and matched to the stated tolerance for up-to-a-week
   delay in fresh listings.
3. **GIS enrichment: New Hanover County's public ArcGIS REST API** for
   parcel adjacency, flood zone, and wetland overlays; a tree canopy raster
   (NLCD or similar) for canopy % — computed deterministically, not via AI.
4. **AI's role kept deliberately narrow**: synthesis/writeup and a vision
   sanity-check on the already-filtered shortlist only — not the primary
   classifier. Keeps cost down and avoids an agent occasionally getting the
   geometry wrong.
5. **Platform: Python/Flask on Railway**, matching the existing surf-widget
   project's stack, with Postgres for state.

## Non-goals (v1)

- Not scraping Zillow/Redfin/Realtor.com directly.
- Not pursuing broker-sponsored MLS access yet.
- Not real-time — weekly cadence is a deliberate design choice.
- Not multi-user or intended for wider distribution.

## Roadmap

| Phase | Scope |
|---|---|
| 1 | Ingestion + storage — RentCast client, Postgres schema, dedupe logic |
| 2 | GIS enrichment — county ArcGIS parcel/adjacency lookup, flood/wetland flags |
| 3 | Canopy scoring — raster clip + % cover calc, old-growth proxy heuristic |
| 4 | Rule-based filter + tunable config (thresholds) |
| 5 | Claude sub-agent — rationale generation + vision check on shortlist only |
| 6 | Digest delivery — weekly email/Slack summary |
| 7 | Deploy to Railway, cron schedule, monitor first few live runs |

## Reference

See `ARCHITECTURE.md` for full technical detail on each component.
