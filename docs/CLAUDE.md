# Canopy — Project Instructions for Claude Code

Read `PROJECT_SUMMARY.md` and `ARCHITECTURE.md` first for full context
before making changes. Don't duplicate their content here — link to them.

## Stack
Python/Flask, deployed on Railway, Postgres for storage.

## Conventions
<!-- Fill in once the repo exists: package manager, test command, lint
     command, directory layout. Keep this section short — a few lines,
     not a manual. -->

## Constraints to respect
- Do not add scraping of Zillow/Redfin/Realtor.com — RentCast is the
  licensed listings source for this project, full stop.
- The Claude sub-agent step (Phase 5) is scoped to synthesis + vision
  sanity-check only. Geometric/GIS/canopy determinations must stay
  rule-based and deterministic — don't let the model make the primary
  adjacency or canopy-% call.
- RentCast free tier is 50 calls/month. Batch listing pulls by zip/radius —
  never loop the sale-listings endpoint per property.
- Weekly cadence is intentional, not a placeholder to "optimize" to daily.

## Where to look
- Data flow and component breakdown: `ARCHITECTURE.md`
- Why decisions were made this way: `PROJECT_SUMMARY.md`
- Build order: `PROJECT_SUMMARY.md` → Roadmap table
