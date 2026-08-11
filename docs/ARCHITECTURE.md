# ARCHITECTURE.md — Canopy (Wilmington Lot Scout)

> Working title: **Canopy**. Rename freely — used here for readability.

## Purpose

An automated pipeline that scans new Wilmington, NC for-sale listings on a
recurring cadence and surfaces the ones whose *lots* match criteria that
keyword search on Zillow/Trulia/Redfin can't express: backing to water, a
park, or unbuildable marsh; large, heavily wooded lots; old-growth tree
canopy neighborhoods. Output is a scored, short-listed digest, not a
full-featured search app.

## System Overview

```
RentCast API  ──▶  Listing Ingest  ──▶  Parcel/GIS Enrichment  ──▶  Canopy Scoring
 (weekly, per        (dedupe,              (New Hanover County         (raster %
  target zip)         store raw)             ArcGIS REST)                cover)
                                                    │
                                                    ▼
                                          Rule-Based Filter
                                       (lot size, canopy %,
                                        adjacency flags)
                                                    │
                                                    ▼
                                     Claude Sub-Agent (candidates only)
                                  vision sanity-check + rationale writeup
                                                    │
                                                    ▼
                                          Digest Generator
                                        (email / Slack message)
```

All state lives in Postgres. Every stage before the sub-agent step is
deterministic — no AI involved until the candidate list is already small.

## Components

### 1. Scheduler
- Railway scheduled job (cron).
- Cadence: **weekly, per target neighborhood/zip** — not daily. This matches
  both the RentCast free-tier call budget and the stated tolerance for
  up-to-a-week delay.

### 2. Listing Ingestion
- **RentCast API**, `/listings/sale` endpoint.
- One call per target zip/radius (not per property) returns all matching
  listings in that area — this is what makes the free tier viable.
- Dedupe against previously seen listing IDs stored in Postgres; only new or
  changed listings flow downstream.

### 3. Parcel & GIS Enrichment
- **New Hanover County ArcGIS REST API** (public, free, no key required).
- For each new listing:
  - Geocode address → parcel ID.
  - Pull parcel geometry.
  - Query adjacent parcels for land-use code / ownership type → flag if a
    neighboring parcel is park, conservation easement, county/city-owned, or
    open water.
  - Pull flood zone and wetland overlay for the parcel itself (marsh/
    unbuildable determination).

### 4. Canopy Scoring
- Tree canopy raster (NLCD canopy layer, or a higher-resolution source if
  the county provides one) clipped to the parcel + a buffer.
- Computes a deterministic % canopy cover — no AI involved.
- **Old-growth proxy**: no canonical "old growth" dataset exists. Approximated
  via parcel record year-built + canopy density combined heuristic. This is
  a documented limitation, not a solved problem — see Known Limitations.

### 5. Rule-Based Filter
- Config-driven thresholds: minimum lot size, minimum canopy %, required
  adjacency flags (water/park/marsh/conservation).
- Produces a short candidate list per run — this is the list that gets
  expensive AI treatment, keeping cost and noise down.

### 6. Claude Sub-Agent (Anthropic API)
Deliberately narrow scope, applied only to the already-filtered candidates:
- **Vision sanity-check**: satellite image crop + street view image, to
  catch things the raster data missed (recent clear-cutting, a "marsh" that
  turns out to be a retention pond, etc.).
- **Rationale synthesis**: turns the structured signals into a plain-English
  writeup — "backs to a county-owned greenway, 78% canopy cover, neighboring
  parcel is a deeded conservation easement."
- **Not** used for the primary geometric/adjacency determination — that
  stays rule-based for reliability, auditability, and cost.

### 7. Storage
- Postgres (Railway add-on).
- Rough schema: `listings`, `parcels`, `scores`, `digest_log`.

### 8. Digest / Delivery
- Weekly email or Slack message: shortlist with photos, MLS link, county GIS
  link, and the sub-agent's rationale for each candidate.

## Tech Stack
- Python / Flask (consistent with the existing surf-conditions widget)
- Railway — hosting, cron scheduling, Postgres add-on
- RentCast API — listings data
- New Hanover County ArcGIS REST API — parcel/adjacency/flood/wetland data
- NLCD (or similar) raster source — tree canopy %
- `rasterio` / `rasterstats` — raster clipping and zonal stats
- Anthropic API (Claude, vision + text) — sub-agent step only
- `requests` / `httpx` — API clients

## API Budget & Constraints
- RentCast free tier: 50 calls/month. Weekly searches across ~4–6 target
  zips/neighborhoods ≈ 20–25 calls/month — comfortable headroom.
- Direct MLS access (IDX/VOW feed) intentionally out of scope for v1 —
  requires a sponsoring broker/agent. Revisit if that relationship exists
  later.
- No scraping of Zillow/Redfin/Realtor.com directly — ToS risk. RentCast
  serves as the licensed intermediary.

## Known Limitations / Open Risks
- No ground-truth "old growth" dataset; heuristic proxy only, will need
  tuning against real results.
- Canopy raster may lag recent clearing by months — the vision sub-agent
  step is the intended mitigation, not a guarantee.
- Weekly cadence is a deliberate tradeoff for API budget, not a technical
  ceiling — could go tighter later on a paid RentCast tier if desired.
- Single-user tool; no auth, multi-tenancy, or scale considerations.

## Future Extensions (explicitly out of scope for v1)
- Broker-sponsored MLS feed for real-time coverage
- SMS/push notification channel
- Historical trend tracking (price cuts, days on market, relisting)
