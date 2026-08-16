# Canopy — Project Instructions for Claude Code

Read `PROJECT_SUMMARY.md` and `ARCHITECTURE.md` first for full context
before making changes. Don't duplicate their content here — link to them.

## Stack
Python/Flask + Postgres, React (Vite) for the rating UI. Deployed on
Railway in production (web service + `run-daily`/`run-digest` Cron Job
services + a Postgres plugin, see README.md's Deploy section). Local dev
uses Docker Compose Postgres and local Flask serving the built frontend.

## Conventions
Package manager: `pip` + `requirements.txt` (backend), `npm` (frontend,
`frontend/`). Test command: `pytest` (backend), `npm test` (frontend,
Vitest). Lint: `ruff check .`. Migrations: Alembic (`alembic upgrade
head`). See `ARCHITECTURE.md` for directory layout.

## Constraints to respect
- Listings come from Zillow saved-search/recommendation alert **emails**,
  polled via IMAP (`canopy/clients/gmail.py`) and parsed
  (`canopy/clients/zillow_email.py`) — RentCast is fully retired. Do not
  add scraping of Zillow/Redfin/Realtor.com's own pages; the boundary is
  receiving your own forwarded/alerted email (fine) vs. fetching a listing
  site's page yourself (not fine, same as before).
- Ingestion (`run-daily`, Stages 1-5) runs **daily** now — RentCast's call
  budget was the only reason it was weekly, and that constraint is gone.
  The digest (`run-digest`, Stage 6) stays **weekly**; don't conflate the
  two schedules or merge them back into one entry point.
- Zillow's alert-email plain text has no explicit property-type field, so
  `is_hard_excluded`'s Condo/Apartment branch doesn't fire for
  email-sourced listings today — a known, documented gap, not a bug to
  silently "fix" by guessing a property type.
- **RentCast-sourced listings (`source = 'rentcast'`) are excluded from
  the rating queue**, alongside the property-type/multi-address hard
  exclusions — `canopy.rating.excluded_listing_ids` filters on
  `source != 'zillow_email'` too. They stay in Postgres as historical
  data (some already have real judgments against them) but can't surface
  via `get_batch`/`get_pair`. Don't delete RentCast rows to "clean up" —
  that's real rating history.
- **Every listing gets a full feature vector; nothing is hard-filtered
  out.** The original rule-based filter collapsed 1025 listings to 2 and
  was retired for exactly this reason (`PROJECT_SUMMARY.md` → Why). Don't
  reintroduce a hard elimination step anywhere in the pipeline.
  **Exception**: `canopy.rating.is_hard_excluded` (property type e.g.
  Condo, or an address spanning multiple house numbers/lots e.g.
  "7401-7429 Starlight Ln") is not this kind of filter — it's a stated
  hard constraint on what counts as a candidate at all (Zach/Andrea will
  never buy a Condo; a multi-address listing isn't a single buildable
  homesite), not a soft threshold on a continuous feature the model
  should learn nuance around. The distinction that matters: it scopes
  the search the same way "for sale" already scopes the listing source,
  it doesn't eliminate a listing based on an uncertain guess at a
  threshold. Enforced in three places — `canopy/cli.py` skips
  GIS/feature/vision compute for excluded listings going forward,
  `canopy/rating.py`'s candidate queries (via `excluded_listing_ids`)
  filter them out of the batch/pair endpoints, and `canopy/model.py`'s
  `compute_digest_slots` filters them out of the weekly digest — so
  listings already processed before an exclusion was added still can't
  surface anywhere without a data migration. Don't extend this pattern
  to anything that's actually a preference (canopy %, lot size,
  adjacency, or "this land looks development-scale" — deliberately
  **not** hard-filtered; see `ARCHITECTURE.md`'s Known Limitations for
  why acreage/price alone isn't a reliable enough signal) — those still
  go through tag-driven hinge classification per `SCORING_MODEL.md` §4,
  never a hard cutoff.
- The Claude vision pass (`canopy/vision.py`) is scoped to structural/
  architecture feature extraction + rationale writeup, run lazily once
  per listing on first view — not a bulk weekly step, and not the
  primary geometric/adjacency/canopy determination (that stays
  rule-based and deterministic). It **never scores, ranks, or votes on
  preference** — rater judgments (`zach`/`andrea`) are the only training
  labels for the preference model (`SCORING_MODEL.md` §10).
- **Never average the two raters' judgments into one model.** Fit
  separate pairwise preference models per rater and combine only at
  digest time, as `min(z_a, z_b)` — never a mean (`SCORING_MODEL.md` §5).
- **Tags never enter the feature vector.** They only shape the model's
  structure and priors (hinge classification, thresholds, coefficient
  priors) — treating a tag as a feature is target leakage
  (`FEATURE_SCHEMA.md` §1).
- **Anchor `ideal`/`limit` minutes are priors, not filters.** They seed
  hinge thresholds for proximity features until enough tagged judgments
  exist to learn real ones (`UI_SPEC.md` §3.1); exceeding `limit` costs
  rank, it never removes a listing.

## Where to look
- Data flow and component breakdown, including known limitations and
  deferred work: `ARCHITECTURE.md`
- Why decisions were made this way, and current build status: `PROJECT_SUMMARY.md`
- Feature vector definition and tag taxonomy: `FEATURE_SCHEMA.md`
- Preference model design (pairwise fitting, hinge expansion, digest
  combination): `SCORING_MODEL.md`
- Rating UI design and API contract: `UI_SPEC.md` (and `frontend/src/`
  for the live implementation — `RatingUI.jsx` in this directory is the
  original historical prototype, kept for reference, not maintained)
