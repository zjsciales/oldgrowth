# ARCHITECTURE.md — Canopy (Wilmington Lot Scout)

> Working title: **Canopy**. Rename freely — used here for readability.

## Purpose

A rating and preference-learning app for two people finding a house in
Wilmington, NC. A daily batch pipeline pulls new listings (from Zillow
saved-search/recommendation alert emails, polled via IMAP) and reduces each
one to a full feature vector — GIS/canopy/market data, deterministic, no
AI. Two raters judge listings through a React UI (swipes, pairwise
comparisons, optional tags); a pairwise preference model — fit separately
per rater — turns those judgments into a ranking. A weekly digest surfaces
the current top picks, the listings most worth rating next, a wildcard,
and where the two raters disagree. Nothing is ever hard-filtered out of
consideration — see `PROJECT_SUMMARY.md` for why that changed from the
original design.

Listings ingestion pivoted from the RentCast API to Zillow alert emails
(`canopy/email_ingest.py`, `canopy/clients/{gmail,zillow_email}.py`) once
RentCast proved too thin (no photos, coarse coverage, a hard 50-call/month
budget) to be the actual bottleneck-fixer it needed to be — real MLS-backed
data with photos was already arriving in an inbox via Zillow's own alert
emails. Everything downstream of ingestion (GIS enrichment, canopy scoring,
feature vectors, the preference model, the rating UI) is unchanged in
spirit; the pivot is the source, not the product.

RentCast was later **restored in a narrower, background-only role**
(`canopy/ingest.py`, `canopy/clients/rentcast.py`, both un-deleted —
see this file's Appendix): it still never supplies rating candidates, but
its listing data fills gaps Zillow's alert emails don't carry (lot size,
year built, property type, MLS info). See Component 2 and
`canopy/rentcast_backfill.py`.

## System Overview

Two loops share the same database: a daily batch pipeline that keeps
listings and models current (with the digest itself staying on its own
weekly schedule), and an interactive rating loop the React app drives over
a JSON API.

```
                          DAILY BATCH PIPELINE (Stages 1-5)
Zillow Alert Emails ──▶ Email Ingest ──▶ Parcel/GIS Enrichment ──▶ Canopy Scoring
 (IMAP poll, parse)   (geocode, dedupe,     (New Hanover County        (raster %
                          store)              ArcGIS REST)                cover)
                          │
                          ▼
                RentCast Collation
             (canopy/rentcast_backfill.py --
              fills gaps by address match)
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

                     RENTCAST REFRESH (background, ~every 5 days,
                          independent schedule, no rating candidates)
                       RentCast API ──▶ RentCast Listing Rows ──▶ (feeds
                       (canopy/ingest.py, source='rentcast')    the collation
                                                                  step above)

                          WEEKLY DIGEST (Stage 6, independent schedule)
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
- Three independent Railway Cron Job services: `python -m canopy.cli
  run-daily` (Stages 1-5), `python -m canopy.cli run-digest` (Stage 6),
  and `python -m canopy.cli run-rentcast` (background RentCast refresh +
  collation), sharing the same Postgres/env vars as the web service.
- Cadence: ingestion is **daily** — RentCast's call budget was the only
  reason it was weekly, and Zillow/Mapbox/NHC GIS/NLCD raster are all
  free/cheap at this volume. The digest stays **weekly** by design
  (a daily email would be noise, not signal), independently schedulable
  now that `canopy/cli.py::run_pipeline` and `run_digest` are split.
  `run-rentcast` runs **every ~5 days**, sized to RentCast's 50-call/month
  free tier (`RENTCAST_MONTHLY_CALL_BUDGET`) — daily or every-72-hours
  would exceed it; see `canopy/config.py`'s comment for the arithmetic.

### 2. Listing Ingestion
- **Zillow saved-search / recommendation alert emails**, polled via IMAP
  (`canopy/clients/gmail.py`) from a Gmail label a filter routes them
  into, parsed from the email's `text/plain` MIME part
  (`canopy/clients/zillow_email.py` — chosen over Zillow's obfuscated
  HTML, which carries the same fields with far more fragility). This is
  still the sole source of rating candidates.
- Dedupe primarily by `zpid` (extracted from the "View this listing" URL),
  falling back to a normalized-address match when no zpid is recoverable;
  see `canopy/email_ingest.py`. Field-presence-aware upsert: a parsed
  value of `None` never overwrites a previously-known value, since an
  alert email (e.g. a price-drop notice) doesn't necessarily restate every
  field. `EmailIngestLog` dedupes at the email level (by Message-ID),
  independent of per-listing dedup. A separate backlog check catches
  listings stuck mid-pipeline from a prior crash
  (`canopy/cli.py::_unenriched_backlog`, `_unfeatured_backlog`).
- Zillow's alert emails don't state an explicit property-type field, so
  the Condo/Apartment hard-exclusion (`canopy.rating.is_hard_excluded`)
  can't fire pre-ingest for this source unless RentCast collation (below)
  backfills `property_type` from a matching row — a documented gap for
  uncollated listings, not a bug. Addresses that fail to geocode
  (new-construction lots, unnumbered addresses) ingest with
  `latitude`/`longitude` left `null`; every downstream stage (GIS
  enrichment, anchor drive times, the vision pass) guards for that and
  imputes rather than crashing.
- Geocoded zip codes outside `TARGET_ZIPS` are logged and the listing is
  flagged `outOfArea` (surfaced in Consider) rather than excluded — a
  Zillow saved search can reach further than RentCast's/this app's
  original coverage area, and that's worth a human glance, not a
  hard-filter decision.
- **RentCast collation** (`canopy/rentcast_backfill.py`): matches
  Zillow-sourced listings to a RentCast row by a suffix-normalized street
  address (RentCast abbreviates suffixes and appends zip; Zillow spells
  them out and omits it — plain string equality doesn't work), and fills
  in `lot_size_sqft`, `year_built`, `property_type`, `county`,
  `mls_name`/`mls_number`, `zip_code`, `listed_date`, and market-history
  raw fields (`daysOnMarket`/`hoa`/`history`) the Zillow row doesn't
  already have — never overwriting a value Zillow supplied. Matched
  listings are flagged `Listing.collated_with_rentcast`, which
  `canopy.rating.get_batch` uses to surface them first in the rating
  queue. Runs automatically for newly-changed listings inside
  `run_pipeline` (Stage 1) and again after every `run-rentcast` refresh;
  `python -m canopy.cli backfill-rentcast` re-runs it against everything
  without polling the API, useful after a matching-logic change.

### 3. Background RentCast Refresh (`canopy/ingest.py`, `canopy/clients/rentcast.py`)
- Retired as the *primary* listings source (see Appendix), restored as a
  background-only feed whose sole purpose is keeping Component 2's
  collation pool from going stale. Confirmed live: right after retirement,
  RentCast's ~1000 rows all shared the exact same `first_seen` timestamp
  (a one-time historical pull, frozen the moment ingestion was retired) —
  match rate against fresh Zillow listings was mostly a staleness
  artifact, not a matching-logic gap.
- Same `fetch_sale_listings_for_zip`/one-call-per-`TARGET_ZIPS`-zip
  design as the original RentCast ingest. RentCast-sourced rows
  (`source = 'rentcast'`) never get GIS enrichment, canopy scoring,
  feature vectors, or vision — those stages only ever run on
  Zillow-sourced listings — and never enter the rating queue (Component
  9). `canopy/cli.py::run_rentcast_weekly` is ingest + collation only.

### 4. Parcel & GIS Enrichment
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

### 5. Canopy Scoring
- NLCD Tree Canopy Cover raster (WCS `GetCoverage`, cached locally),
  zonal stats via `rasterio.mask`. Deterministic, no AI.
- A raster-masking bug (bounding-box fill pixels outside the actual
  polygon were silently counted as "0% canopy") was found and fixed
  during the rating-pivot build — see Known Limitations for what it
  means for historical data.
- **Old-growth proxy**: no canonical "old growth" dataset exists;
  approximated via parcel year-built + canopy density. Documented
  limitation, not a solved problem.

### 6. Feature Vector Computation
- `canopy/features.py`, per `FEATURE_SCHEMA.md`. Every listing gets a
  full vector — lot/surroundings, canopy (parcel *and* neighborhood-
  buffer, a deliberate split so "wooded street, open lot" is visible),
  structure/market, proximity rollups. Missing values are imputed and
  flagged in `imputed_fields`, never used to eliminate a listing.
- `median_year_built_buffer` is computed from our own already-ingested
  `Listing` rows (no NHC layer exposes year-built — checked live), and
  anchor proximity rollups (`min_drive_beach` etc.) are computed on the
  fly from `ListingAnchorTime`, not persisted as columns.
- `fronting_road_class` is populated from New Hanover County's own Roads
  layer (`RDCLASS` field, `canopy/clients/nhc_gis.py`'s
  `RDCLASS_TO_ROAD_CLASS`) — not OSM. The rest of the road/position group
  (`dist_to_arterial_m`, `is_cul_de_sac`, `is_dead_end`,
  `through_traffic_proxy`, `front_setback_ft`) remain reserved, unpopulated
  columns — OpenStreetMap integration is still deferred for those (see
  Known Limitations).
- **Real parcel outline + road geometry for `ParcelPlate`**
  (`ListingFeatures.extra["parcel_outline"]`/`["road_edges"]`, computed by
  `canopy/clients/nhc_gis.py::simplify_parcel_outline_ft` and the
  road-capture logic inside `compute_boundary_features`): a simplified,
  centroid-relative, foot-rounded version of the real county parcel
  polygon, plus per-compass-side real road centerline geometry/name/class
  for whichever sides actually front a road. Lets the rating UI draw the
  lot's true shape and the real street(s) it sits on instead of a
  placeholder rectangle and flat compass bands — see Component 8 and
  `docs/UI_SPEC.md`'s revised §5.

### 7. Lazy Vision Pass (`canopy/vision.py`)
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

### 8. Rating UI + API
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

### 9. Preference Model (`canopy/model.py`)
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

### 10. Storage
- Postgres. Core listing pipeline: `listings`, `parcels`, `scores`,
  `digest_log`. Preference layer: `listing_features`, `anchors`,
  `listing_anchor_times`, `raters`, `judgments`, `tags`, `judgment_tags`,
  `judgment_anchors`, `pairwise_comparisons`, `model_runs`,
  `preference_scores` (named to avoid colliding with the existing
  `scores` table, which stays deterministic-canopy-only). Email-ingestion
  layer: `email_ingest_log` (Message-ID-keyed dedup, independent of
  per-listing dedup — see Component 2).
- `listings.source` distinguishes `'rentcast'` (background collation feed
  only, never a rating candidate) from `'zillow_email'` (current, sole
  source of rating candidates). `canopy.rating.excluded_listing_ids`
  — the single choke point behind `get_batch`/`get_pair`/`_random_pair`
  in `canopy/rating.py` — excludes anything not `source ==
  'zillow_email'` from the rating queue, alongside the property-type/
  multi-address hard exclusions. RentCast rows are never deleted (they're
  real historical rating data — some already have judgments against
  them, and current rows keep flowing in via `run-rentcast`) but can't
  surface as new rating candidates.
- `listings.collated_with_rentcast` — set by
  `canopy/rentcast_backfill.py` when a Zillow-sourced row was matched to
  a RentCast row and at least one gap field was ever filled from it.
  `canopy.rating.get_batch` surfaces collated listings first, since they
  carry a more complete feature vector.

### 11. Digest / Delivery
- `canopy/digest.py`, built from `canopy/model.py::compute_digest_slots`
  — not a filter's pass/fail list. Sections: top-ranked (~70%),
  uncertain/most-informative-to-rate (~20%), wildcard (~10%), and a
  dedicated "you two disagree about these" section (shows a
  "still calibrating" note before both raters have a fitted model).
  `DigestLog` is a plain audit log, not a suppression filter — a
  listing can resurface if its rank or uncertainty changes week to
  week, which is correct for a ranking system.

## Tech Stack
- Python / Flask, Postgres — Railway in production (web service + three
  Cron Job services + Postgres plugin, see README.md's Deploy section),
  Docker Compose for local dev
- React + Vite (`frontend/`) — no Tailwind, a small literal CSS file for
  the handful of layout utility classes the UI prototype used
- `numpy` / `scipy` — the preference model's fitting/bootstrap machinery
- Gmail IMAP + Zillow alert emails — sole source of rating candidates
- RentCast API — background-only collation feed, restored after full
  retirement as the primary source; see Appendix and Component 3
- New Hanover County ArcGIS REST API — parcel/boundary/flood/wetland data
- NLCD raster (`rasterio`) — tree canopy %
- Anthropic API (Claude, vision + text) — lazy per-listing structural
  extraction + rationale only, never scoring
- Mapbox — satellite/location-map imagery for the vision pass and photo
  fallback, geocoding for anchors and email-sourced listing addresses
- `requests` / `httpx` / stdlib `imaplib` — API/email clients

## API Budget & Constraints
- Gmail IMAP polling has no per-call cost, and Anthropic/Mapbox calls are
  bounded by the lazy-vision design (once per listing, ever, not per
  week) rather than a quota. RentCast's 50-call/month free tier no longer
  gates the primary ingestion path, but it does still gate
  `run-rentcast`'s cadence directly — see Component 1/3 and
  `canopy/config.py`'s `RENTCAST_MONTHLY_CALL_BUDGET` comment for the
  math (weekly-ish is comfortable, daily or every-72-hours is not).
- No scraping of Zillow/Redfin/Realtor.com's own pages — the boundary is
  receiving your own forwarded/alerted email (fine) vs. fetching a
  listing site's page yourself (not fine).

## Known Limitations / Open Risks

- **New Hanover County's Roads layer essentially never registers a
  parcel's "road" edge in practice** (found live, 2026-08-17, while
  wiring up real road-edge geometry for `ParcelPlate`): checked across
  every listing with cached `edges` data (116 rows) and a separate random
  sample of enriched parcels — 0/116 have ever had `edges` classify any
  compass side as `"road"`. Root cause: `BOUNDARY_TOUCH_FT = 5` (a
  5ft "digitizing-gap allowance," appropriate for adjacent *polygon*
  features like parks/water/easements, which should share almost the
  same boundary line) is the same tolerance used for road *centerlines*,
  which are inherently offset from the property line by roughly half a
  street's right-of-way width (often 15-30+ft for a residential street)
  — not a digitizing error, a real physical gap. This isn't a new
  regression — `compute_boundary_features`'s road-touch logic predates
  the parcel-outline/road-geometry work and always used this tolerance;
  it just never surfaced as a visible problem until real road-edge
  rendering made the "we never actually detect roads" fact obvious. Real
  road name/classification data genuinely exists and is correctly
  captured wherever a road-touch *does* register (tested against real
  live county data — see `tests/test_nhc_gis.py`'s
  `test_compute_boundary_features_captures_real_road_edge_geometry`); the
  gap is purely in the touch-distance threshold. A fix (a separate, larger
  tolerance specifically for road-touch detection, distinct from
  `BOUNDARY_TOUCH_FT`) is a reasonable follow-up but touches
  `protected_perimeter_ratio`/`abuts_buildable_private` — real,
  already-used ranking inputs with judgments/comparisons trained against
  their current values — so it wasn't made unilaterally as part of this
  change; flagged here for a deliberate follow-up decision instead.
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
- **RentCast-sourced listings are refreshed only every ~5 days**
  (`run-rentcast`, Component 1/3), not daily like the Zillow path — a
  deliberate tradeoff for the 50-call/month free tier, not an oversight.
  A RentCast row can lag up to ~5 days behind a real status/price change.
  Not a correctness problem for rating (RentCast rows are excluded from
  the queue regardless, see Component 10) but worth knowing if you ever
  query `listings` by `status` across both sources, or wonder why a
  RentCast-side match briefly showed stale data.
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
- OpenStreetMap road/position features (`dist_to_arterial_m`,
  cul-de-sac/dead-end detection, through-traffic proxy) — reserved
  columns exist, not yet populated. `fronting_road_class` is no longer in
  this list — it's populated from the county's own Roads layer instead
  (see Component 6).
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

## Appendix: RentCast's Role Over Time

RentCast has occupied three different roles in this project, in order.
Not all of the detail below describes current behavior — read each bullet
in its own time frame.

1. **Original design: primary listings source.** RentCast API free tier
   (50 calls/month) — chosen over ATTOM (sales-call-gated) and unofficial
   scrapers (ToS risk). Weekly searches across the 6 target zips
   (`TARGET_ZIPS`) cost ≈24-26 calls/month; cadence was weekly, sized
   directly to that budget, not a reflection of how fresh the underlying
   market data actually was. RentCast's batched-by-zip sale-listings
   endpoint had no photo field at all, and no zoning/description field
   either (relevant to the "development-scale land" open question in
   Known Limitations above) — a per-listing detail call might have had a
   photo, but calling RentCast per-property was explicitly ruled out by
   the budget constraint. This is why Consider's photo slot originally
   showed only a location map, before `photoUrl` (Zillow-hosted CDN
   images) became available via the email pivot below.
2. **Fully retired**, in favor of Zillow alert emails — see this file's
   Purpose section for why. `canopy/clients/rentcast.py`/`canopy/ingest.py`
   were deleted; existing RentCast rows stayed in Postgres as static
   historical data, excluded from the rating queue.
3. **Restored as a background-only weekly-ish feed.** Investigating a low
   Zillow-to-RentCast match rate in `canopy/rentcast_backfill.py`'s
   collation found it was mostly caused by RentCast's rows all sharing
   one frozen `first_seen` timestamp from the retirement-day pull, not a
   fundamental data-quality gap — so `canopy/clients/rentcast.py`/
   `canopy/ingest.py` were restored (same design as role 1: one call per
   `TARGET_ZIPS` zip, same 50-call/month budget) to keep that pool fresh,
   run every ~5 days via `canopy.cli.run_rentcast_weekly`. RentCast rows
   still never enter the rating queue and never get GIS enrichment/canopy
   scoring/feature vectors/vision — this role exists purely to feed
   Component 2's collation step. See Component 3 for current detail.
