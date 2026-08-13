# ARCHITECTURE.md — Canopy (Wilmington Lot Scout)

> Working title: **Canopy**. Rename freely — used here for readability.

## Purpose

A rating and preference-learning app for two people finding a house in
Wilmington, NC. A weekly batch pipeline pulls new listings and reduces
each one to a full feature vector — GIS/canopy/market data, deterministic,
no AI. Two raters judge listings through a React UI (swipes, pairwise
comparisons, optional tags); a pairwise preference model — fit separately
per rater — turns those judgments into a ranking. A weekly digest surfaces
the current top picks, the listings most worth rating next, a wildcard,
and where the two raters disagree. Nothing is ever hard-filtered out of
consideration — see `PROJECT_SUMMARY.md` for why that changed from the
original design.

## System Overview

Two loops share the same database: a weekly batch pipeline that keeps
listings and models current, and an interactive rating loop the React app
drives over a JSON API.

```
                         WEEKLY BATCH PIPELINE
RentCast API ──▶ Listing Ingest ──▶ Parcel/GIS Enrichment ──▶ Canopy Scoring
 (per target zip)  (dedupe, store)    (New Hanover County        (raster %
                                        ArcGIS REST)                cover)
                                              │
                                              ▼
                                  Feature Vector Computation
                                (FEATURE_SCHEMA.md -- every listing,
                                       nothing eliminated)
                                              │
                                              ▼
                          Preference Model Refit (per rater, separately)
                         pairwise logistic regression + tag-driven hinge
                              basis expansion (SCORING_MODEL.md)
                                              │
                                              ▼
                            Digest Slot Selection + Email
                         (top-ranked / uncertain / wildcard / disagree)

                          INTERACTIVE RATING LOOP
React UI (Vite) ──▶ JSON API (canopy/api.py) ──▶ Judgments / Comparisons / Anchors
      ▲                     │                              │
      │                     ▼                              ▼
      └── ListingCard ── Lazy Vision Pass          feeds the next
          (edges, canopy,   (first view only,      Preference Model Refit
           drives, ...)      structure + rationale,
                              never votes)
```

All state lives in Postgres. Everything before the vision pass is
deterministic — no AI involved in the primary geometric/adjacency/canopy
determination, ever. The vision pass and the preference model are the only
two places a listing's ranking can be influenced by something other than
hard GIS/raster/market data and the raters' own judgments — and the vision
pass never ranks, it only describes and sanity-checks.

## Components

### 1. Scheduler
- macOS `launchd` (`com.canopy.weekly.plist`), weekly, currently local.
  A Railway scheduled job is the planned next step once a production
  Postgres is provisioned there (see `PROJECT_SUMMARY.md` decision 6) —
  the pipeline code itself doesn't change, only where it runs.
- Cadence: **weekly** — matches the RentCast free-tier call budget and the
  stated tolerance for up-to-a-week delay. Deliberate, not a placeholder.

### 2. Listing Ingestion
- **RentCast API**, `/listings/sale` endpoint.
- One call per target zip returns all matching listings — this is what
  makes the free tier viable.
- Dedupe against previously seen listing IDs; only new/changed listings
  flow downstream. A separate backlog check catches listings stuck
  mid-pipeline from a prior crash (`canopy/cli.py::_unenriched_backlog`,
  `_unfeatured_backlog`).

### 3. Parcel & GIS Enrichment
- **New Hanover County ArcGIS REST API** (public, free, no key).
- Point-in-polygon lookup for the parcel, then two levels of boundary
  analysis:
  - `canopy/enrich.py` / `clients/nhc_gis.py::enrich_parcel` — the
    original coarse "any hit within a 50ft buffer" adjacency flags
    (`Parcel.adjacent_water` etc.), still used for the Stage-2 `Parcel`
    record.
  - `clients/nhc_gis.py::compute_boundary_features` — finer-grained: what
    fraction of the parcel's *own* perimeter actually touches water,
    marsh, park, conservation easement, or road (vs. buildable-private,
    the "someone can build behind it" risk case), plus a dominant type
    per compass side for the rating UI's parcel plate. Backed by a real
    county building-footprint layer (`Layers/BuildingFootprints`) for
    `rear_open_distance_ft` — found live during development, not a
    proxy.
- Flood zone and wetland overlay/percentage for the parcel itself.

### 4. Canopy Scoring
- NLCD Tree Canopy Cover raster (WCS `GetCoverage`, cached locally),
  zonal stats via `rasterio.mask`. Deterministic, no AI.
- A raster-masking bug (bounding-box fill pixels outside the actual
  polygon were silently counted as "0% canopy") was found and fixed
  during the rating-pivot build — see Known Limitations for what it
  means for historical data.
- **Old-growth proxy**: no canonical "old growth" dataset exists;
  approximated via parcel year-built + canopy density. Documented
  limitation, not a solved problem.

### 5. Feature Vector Computation
- `canopy/features.py`, per `FEATURE_SCHEMA.md`. Every listing gets a
  full vector — lot/surroundings, canopy (parcel *and* neighborhood-
  buffer, a deliberate split so "wooded street, open lot" is visible),
  structure/market, proximity rollups. Missing values are imputed and
  flagged in `imputed_fields`, never used to eliminate a listing.
- `median_year_built_buffer` is computed from our own already-ingested
  `Listing` rows (no NHC layer exposes year-built — checked live), and
  anchor proximity rollups (`min_drive_beach` etc.) are computed on the
  fly from `ListingAnchorTime`, not persisted as columns.
- Road/position features (`fronting_road_class`, `dist_to_arterial_m`,
  etc.) are reserved columns, not yet populated — OpenStreetMap
  integration is deferred (see Known Limitations).

### 6. Lazy Vision Pass (`canopy/vision.py`)
- Runs **once per listing, on first view** (triggered by `GET
  /api/batch`/`/api/pair`), not as a bulk weekly step — running Claude
  vision on the full weekly listing volume would blow past this
  project's cost discipline.
- Extracts structural/architecture features (style, exterior material,
  garage type, renovation recency) and writes a plain-English rationale,
  sanity-checking the satellite image against the structured signals
  (catches things like active construction near land flagged as
  protected).
- **Never** the primary geometric/adjacency/canopy call, and never votes
  on preference — SCORING_MODEL.md §10 is explicit that only rater
  judgments are training labels.

### 7. Rating UI + API
- **Frontend**: React + Vite (`frontend/`), built to static assets and
  served by the same Flask process (`canopy/app.py`) — one local
  process, no CORS. Four tabs: Consider (swipe triage), Compare
  (forced-choice pairwise), Places (shared anchor list), Patterns (live
  tag credit/blame preview of the weights dashboard). Signature element:
  `ParcelPlate`, a deterministically-seeded SVG site plan showing canopy
  coverage and compass-edge classification.
- **API**: `canopy/api.py`, a Flask Blueprint (`/api/*`) over
  `canopy/rating.py`'s business logic — batch/pair selection (cold-start
  stratified sampling, then active selection once a model exists),
  judgment/comparison recording (server-side tag-polarity validation —
  this is now a real trust boundary), anchor CRUD with server-side
  geocoding (Mapbox).

### 8. Preference Model (`canopy/model.py`)
- Pairwise logistic regression on feature *differences*
  (`P(a≻b) = σ(w·(x_a−x_b))`), fit separately per rater, ridge-
  regularized toward a hand-set cold-start prior (`model_prior.py`) —
  not toward zero — with decaying grip as real judgment pairs
  accumulate.
- Tag-driven hinge basis expansion: features get classified hygiene/
  delighter/linear from Yes/No tag credit-blame asymmetry, with
  dealbreaker/delight thresholds read directly off tagged listings'
  raw feature values (this is the concrete answer to "what canopy %
  are we comfortable with" that a single hand-set number couldn't give).
- Bootstrap (200 resamples) for coefficient confidence intervals and
  per-listing prediction variance; near-deterministic vetoes for
  features present in ≥90% of a rater's rejections.
- Hand-rolled in numpy/scipy, deliberately not scikit-learn — ridge
  toward a nonzero prior isn't an sklearn built-in anyway, and this
  keeps the model from quietly growing into something less
  interpretable than the data volume warrants.
- Two raters' models are **never averaged**. The weekly digest combines
  them as `joint_score = min(z_a, z_b)`.

### 9. Storage
- Postgres. Core listing pipeline: `listings`, `parcels`, `scores`,
  `digest_log`. Preference layer: `listing_features`, `anchors`,
  `listing_anchor_times`, `raters`, `judgments`, `tags`, `judgment_tags`,
  `judgment_anchors`, `pairwise_comparisons`, `model_runs`,
  `preference_scores` (named to avoid colliding with the existing
  `scores` table, which stays deterministic-canopy-only).

### 10. Digest / Delivery
- `canopy/digest.py`, built from `canopy/model.py::compute_digest_slots`
  — not a filter's pass/fail list. Sections: top-ranked (~70%),
  uncertain/most-informative-to-rate (~20%), wildcard (~10%), and a
  dedicated "you two disagree about these" section (shows a
  "still calibrating" note before both raters have a fitted model).
  `DigestLog` is a plain audit log, not a suppression filter — a
  listing can resurface if its rank or uncertainty changes week to
  week, which is correct for a ranking system.

## Tech Stack
- Python / Flask, Postgres (Docker Compose locally; Railway planned next)
- React + Vite (`frontend/`) — no Tailwind, a small literal CSS file for
  the handful of layout utility classes the UI prototype used
- `numpy` / `scipy` — the preference model's fitting/bootstrap machinery
- RentCast API — listings data
- New Hanover County ArcGIS REST API — parcel/boundary/flood/wetland data
- NLCD raster (`rasterio`) — tree canopy %
- Anthropic API (Claude, vision + text) — lazy per-listing structural
  extraction + rationale only, never scoring
- Mapbox — satellite imagery for the vision pass, geocoding for anchors
- `requests` / `httpx` — API clients

## API Budget & Constraints
- RentCast free tier: 50 calls/month. Weekly searches across 6 target
  zips ≈ 24-26 calls/month — comfortable headroom.
- No scraping of Zillow/Redfin/Realtor.com directly — RentCast is the
  licensed intermediary.
- Anthropic/Mapbox calls are bounded by the lazy-vision design (once per
  listing, ever, not per week) rather than a hard budget ceiling.

## Known Limitations / Open Risks

- No ground-truth "old growth" dataset; `canopy_age_proxy` is a heuristic,
  same caveat as the original v1 design.
- `rear_open_distance_ft` falls back to a centroid-to-boundary proxy on
  parcels with no building footprint on record yet (e.g. pre-construction
  lots); real footprint data is used when available.
- `median_year_built_buffer` coverage is necessarily partial — only areas
  where we've already ingested listings — since no NHC GIS layer exposes
  year-built (confirmed live against 4 candidate layers).
- Canopy raster may lag recent clearing by months; the lazy vision pass
  is the intended mitigation, not a guarantee. A real, historical
  instance of this: the raster's own zero-fill masking bug (see below)
  meant canopy % was silently deflated for most non-rectangular parcels
  until fixed during this pivot — rescoring all 1025 real listings after
  the fix moved the count clearing a 40% canopy threshold from a much
  smaller number to 148, which was likely a bigger contributor to the
  original 1025→2 collapse than the hard-filter design itself.
- **GIS boundary/footprint queries are slow per listing** (~3-14s,
  several sequential ArcGIS REST calls) — fine for the weekly incremental
  batch, but a full backlog run against ~1000 listings takes multiple
  hours. Needs batching/parallelization if ingest volume grows.
- **Preference-model scoring recomputes its own bootstrap independently
  of fitting's bootstrap** (`canopy/model.py`, an intentional
  independent-callability tradeoff) — roughly 2x the bootstrap compute
  per weekly refit. Fast at current data volume; worth profiling once
  judgment counts climb into the hundreds/thousands.
- **Anchor drive times are a haversine proxy**, not real routing
  (`ListingAnchorTime.is_proxy`), until routing integration lands.
  Likely meaningfully wrong wherever the road network isn't a straight
  shot — a real concern for a coastal market with river/Intracoastal
  crossings.
- **Local dev environment**: macOS AirPlay Receiver squats on port 5000,
  which broke Vite's dev-server API proxy in a non-obvious way (proxying
  "localhost" resolved to the IPv6 listener AirPlay owns, not Flask's
  IPv4 bind) in addition to the more obvious direct-Flask-on-5000
  conflict. Both worked around; worth remembering "localhost" resolution
  on macOS isn't reliably IPv4-first if this class of bug resurfaces.
- `frontend/`'s `npm audit` currently reports vulnerabilities confined to
  Vite's dev-server toolchain (esbuild's dev-server-only CORS issue) —
  not a runtime risk for a local-only single-user app; fixing requires a
  breaking Vite major-version bump, deferred.
- No auth/multi-tenancy — fine for a two-person personal tool, would need
  real hardening before any wider use.
- **No reliable "is this land commercial/multi-home-development-scale"
  signal exists across the whole market.** Investigated NHC's GIS
  zoning layers (`Layers/Zoning_base/FeatureServer/3`,
  `Thematic/PlanNHC_Zoning`) as the obvious authoritative source; found
  live that in-city parcels return a `"CITY"` placeholder instead of a
  real zoning code — the county's zoning layer only covers unincorporated
  county land, not Wilmington city limits, which is most of TARGET_ZIPS.
  A complete fix would need the City of Wilmington's own separate GIS
  system, out of scope for now. RentCast's payload has no zoning/
  description field either. Lot size/price alone are too uncertain to
  hard-filter on (same failure mode as the original retired filter —
  some legitimate large single-homesite listings exist up to ~2.5
  acres in real data). What *is* implemented: an unambiguous, verified-
  zero-false-positive regex catching listings whose address spans
  multiple house numbers/lots (e.g. "7401-7429 Starlight Ln"), which by
  definition aren't a single buildable homesite — see
  `canopy.rating.MULTI_ADDRESS_PATTERN`. The fuzzier remaining cases
  (single-address, huge acreage, on a commercial corridor) are a
  candidate for a future tag (e.g. "development-scale land") feeding
  the existing hinge-threshold learning, rather than a hard cutoff.

## Future Extensions (explicitly out of scope for now)
- OpenStreetMap road/position features (`fronting_road_class`,
  `dist_to_arterial_m`, cul-de-sac/dead-end detection, through-traffic
  proxy) — reserved columns exist, not yet populated.
- Real drive-time routing, replacing the haversine proxy.
- Railway redeploy (see `PROJECT_SUMMARY.md` decision 6).
- UI polish items explicitly deferred in `UI_SPEC.md` §7: free-text
  capture on `other_yes`/`other_no`, address autocomplete on the Places
  tab (raw geocoding already works, just not the autocomplete UX),
  offline judgment queueing, keyboard shortcuts in Consider, undo on the
  last judgment.
- Broker-sponsored MLS feed for real-time coverage.
- SMS/push notification channel.
- **Real front-elevation listing photos.** RentCast's sale-listings
  endpoint (the batched-by-zip one we're allowed to call) has no photo
  field at all — confirmed against real stored payloads. A per-listing
  detail call might have one, but calling RentCast per-property is
  explicitly ruled out (`CLAUDE.md`). The only real source found is
  Google Street View Static API (~$0.007/panorama, trivial cost at this
  scale, fetched lazily like vision) — deferred because it's a new paid
  API/key relationship, and Street View coverage has real gaps for
  newer or private-road subdivisions that would need a graceful
  fallback. In the meantime, Consider's photo slot shows a ~1mi-radius
  location map (`canopy/clients/mapbox.py`'s `fetch_location_map`) —
  free (same Mapbox relationship already in use), gives locational
  context, but isn't a photo of the house itself.
