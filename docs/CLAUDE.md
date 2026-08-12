# Canopy — Project Instructions for Claude Code

Read `PROJECT_SUMMARY.md` and `ARCHITECTURE.md` first for full context
before making changes. Don't duplicate their content here — link to them.

## Stack
Python/Flask + Postgres, React (Vite) for the rating UI. Currently
developed and run locally (Docker Compose Postgres, local Flask serving
the built frontend, macOS `launchd` for the weekly cron) — a Railway
redeploy is planned next, not yet done. Don't assume Railway-specific
infra (env vars, add-ons, scheduled jobs) exists until that migration
actually happens.

## Conventions
Package manager: `pip` + `requirements.txt` (backend), `npm` (frontend,
`frontend/`). Test command: `pytest` (backend), `npm test` (frontend,
Vitest). Lint: `ruff check .`. Migrations: Alembic (`alembic upgrade
head`). See `ARCHITECTURE.md` for directory layout.

## Constraints to respect
- Do not add scraping of Zillow/Redfin/Realtor.com — RentCast is the
  licensed listings source for this project, full stop.
- RentCast free tier is 50 calls/month. Batch listing pulls by zip/radius
  — never loop the sale-listings endpoint per property.
- Weekly cadence is intentional, not a placeholder to "optimize" to daily.
- **Every listing gets a full feature vector; nothing is hard-filtered
  out.** The original rule-based filter collapsed 1025 listings to 2 and
  was retired for exactly this reason (`PROJECT_SUMMARY.md` → Why). Don't
  reintroduce a hard elimination step anywhere in the pipeline.
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
