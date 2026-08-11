# Canopy — Wilmington Lot Scout

See `docs/PROJECT_SUMMARY.md` and `docs/ARCHITECTURE.md` for what this is
and why. `docs/CLAUDE.md` has constraints for AI-assisted changes to this
repo.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then fill in RENTCAST_API_KEY, ANTHROPIC_API_KEY, SMTP_*

docker compose up -d   # local Postgres on localhost:5433
```

## Run

```bash
source .venv/bin/activate
python -m flask --app canopy.app run   # health check at /healthz

python -m canopy.cli run-weekly --dry-run   # dry-run: skips sending email, logs digest HTML instead
python -m canopy.cli run-weekly             # live run: ingests, enriches, scores, filters, emails
```

## Deploy (Railway)

1. `railway init` in this directory (or link an existing project with `railway link`).
2. `railway add` a Postgres plugin — Railway injects `DATABASE_URL` automatically;
   `canopy/config.py` reads it, overriding the local-dev default.
3. Set the remaining env vars from `.env.example` in the Railway dashboard
   (`RENTCAST_API_KEY`, `ANTHROPIC_API_KEY`, `MAPBOX_API_KEY`, `SMTP_*`,
   `DIGEST_TO_EMAIL`, `TARGET_ZIPS`). Do **not** set `DATABASE_URL` yourself —
   Railway's Postgres plugin already provides it.
4. `railway up` to deploy. `railway.json`'s `preDeployCommand` runs
   `alembic upgrade head` before each deploy; the web process
   (`gunicorn canopy.app:app`, per `Procfile`) serves `/healthz` so Railway
   has something to health-check.
5. Add a second Railway service for the weekly job: same repo/image, but as
   a **Cron Job** service (Railway dashboard → New → Cron Job) with start
   command `python -m canopy.cli run-weekly` and a weekly schedule (e.g.
   `0 13 * * 1` for Monday 9am ET). Cron services share the same env vars
   and Postgres as the web service when attached to the same project.
6. Before trusting the cron: trigger the cron service manually once from
   the Railway dashboard and confirm a digest email arrives, then monitor
   the first couple of scheduled runs.

## Tests

```bash
pytest
```

Tests run against recorded fixtures in `tests/fixtures/` — never against
live RentCast/ArcGIS/Anthropic APIs (RentCast's free tier is capped at
50 calls/month).
