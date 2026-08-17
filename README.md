# Canopy — Wilmington Lot Scout

See `docs/PROJECT_SUMMARY.md` and `docs/ARCHITECTURE.md` for what this is
and why. `docs/CLAUDE.md` has constraints for AI-assisted changes to this
repo.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # then fill in ANTHROPIC_API_KEY, MAPBOX_API_KEY, RENTCAST_API_KEY, SMTP_*

docker compose up -d   # local Postgres on localhost:5433
```

Frontend (built once, or after any change under `frontend/src/`):

```bash
cd frontend
npm install
npm run build   # outputs to canopy/static/dist, which Flask serves
```

## Run

```bash
source .venv/bin/activate
PORT=5050 python -m flask --app canopy.app run   # port 5000 conflicts with macOS AirPlay Receiver
# open http://127.0.0.1:5050 -- serves the built React app + /api/*, health check at /healthz

python -m canopy.cli run-daily              # Stages 1-5: poll Gmail for Zillow alerts, enrich, score, compute features, refit both raters' models
python -m canopy.cli run-digest --dry-run   # Stage 6, dry-run: skips sending email, logs digest HTML instead
python -m canopy.cli run-digest             # Stage 6, live: emails the weekly digest from whatever's already accumulated
python -m canopy.cli run-rentcast           # Background: refresh RentCast rows (no rating candidates), then re-collate against Zillow listings
python -m canopy.cli backfill-rentcast      # One-off: re-run collation against existing RentCast rows without polling the API
```

`run-daily`, `run-digest`, and `run-rentcast` are independently schedulable (see Deploy below) -- ingestion runs daily now that RentCast's call budget is no longer a constraint on the *primary* source, the digest stays weekly, and `run-rentcast` runs every ~5 days (see `canopy/config.py`'s `RENTCAST_MONTHLY_CALL_BUDGET` comment for the math).

### RentCast: background-only collation feed

RentCast was fully retired as the primary listings source (see
`docs/ARCHITECTURE.md`'s Appendix) and later restored in a narrower role:
`run-rentcast` keeps a background set of RentCast listings fresh purely so
`canopy/rentcast_backfill.py` can match Zillow-sourced listings to a
RentCast row by address and fill in fields Zillow's alert emails don't
carry (lot size, year built, property type, MLS info, market history).
RentCast-sourced listings never enter the rating queue and never get GIS
enrichment/canopy scoring/vision -- only Zillow-sourced listings do.
Matched listings are flagged `collated_with_rentcast` and surface first
in the Consider queue, since they carry a more complete feature vector.
Zillow listings whose geocoded zip falls outside `TARGET_ZIPS` are logged
and flagged `outOfArea` in the UI (not excluded -- just called out, since
they're outside RentCast's -- and this app's original -- coverage area).

### Gmail setup for Zillow alert ingestion

1. Sign up for a Zillow saved search (or "homes we think you'll love"
   recommendations) using the Gmail address in `SMTP_USER`.
2. In Gmail, create a filter matching mail from `*@mail.zillow.com` (or
   scope it to the specific saved-search subject) that applies the label
   set in `GMAIL_IMAP_LABEL` (default `canopy-listings`) and skips the
   inbox if you don't want to see them there too.
3. Make sure IMAP is enabled for the account (Gmail Settings → Forwarding
   and POP/IMAP → Enable IMAP) and that `SMTP_PASS` is an App Password
   (same one already used for digest sending) -- `canopy/clients/gmail.py`
   reuses `SMTP_USER`/`SMTP_PASS` for IMAP login.
4. `canopy/clients/gmail.py` tracks what it's already ingested with a
   custom IMAP flag, not Gmail's `\Seen` flag, so reading an alert on your
   phone never stops ingestion.

For active frontend iteration, run `flask run --port 5000` (no PORT
override — `frontend/vite.config.js`'s dev proxy targets `127.0.0.1:5000`
explicitly) in one terminal and `npm run dev --prefix frontend` in
another; the Vite dev server proxies `/api/*` to Flask.

## Deploy (Railway)

`railway.json` builds from the repo's `Dockerfile` (multi-stage: `node:20-slim`
builds the frontend into `canopy/static/dist/`, then `python:3.12-slim` installs
`requirements.txt` and copies the app + built assets in). Nixpacks was tried
first and abandoned after several failed deploys — its auto-detected Python
phase and a hand-added Node phase kept fighting each other (a custom
`nixPkgs`/`phases.install` override replaces rather than merges with the
provider's own, and even after separating them, `libexpat` — a runtime dep of
rasterio/GDAL, needed for XML-based raster formats — never reliably reached
the running process via Nix's `LD_LIBRARY_PATH` wiring). The Dockerfile
installs `libexpat1` via `apt-get` directly, which registers it in the OS's
standard linker cache; verified locally end-to-end with `docker build` +
`docker run` against real Postgres (`/healthz`, `/`, and `/api/tags` all
returned correctly) before trusting it to Railway.

1. `railway init` in this directory (or link an existing project with `railway link`).
2. `railway add` a Postgres plugin — Railway injects `DATABASE_URL` automatically;
   `canopy/config.py` reads it, overriding the local-dev default.
3. Set the remaining env vars from `.env.example` in the Railway dashboard
   (`ANTHROPIC_API_KEY`, `MAPBOX_API_KEY`, `RENTCAST_API_KEY`, `SMTP_*`,
   `DIGEST_TO_EMAIL`, `GMAIL_IMAP_LABEL`, `TARGET_ZIPS`). Do **not** set
   `DATABASE_URL` yourself — Railway's Postgres plugin already provides it.
4. `railway up` to deploy. `railway.json`'s `preDeployCommand` runs
   `alembic upgrade head` before each deploy; the web process
   (`gunicorn canopy.app:app`, per `Procfile`) serves `/healthz` so Railway
   has something to health-check.
5. Add three more Railway services, all as **Cron Job** services (Railway
   dashboard → New → Cron Job), sharing the same repo/image, env vars, and
   Postgres as the web service:
   - `python -m canopy.cli run-daily` on a daily schedule (e.g. `0 12 * * *`
     for 8am ET) -- Stages 1-5.
   - `python -m canopy.cli run-digest` on a weekly schedule (e.g.
     `0 13 * * 1` for Monday 9am ET) -- Stage 6 only.
   - `python -m canopy.cli run-rentcast` every ~5 days (e.g. `0 11 */5 * *`)
     -- background RentCast refresh + collation only, sized to stay under
     RentCast's 50-call/month free tier (see `canopy/config.py`'s
     `RENTCAST_MONTHLY_CALL_BUDGET` comment; daily or every-72-hours would
     exceed it).
6. Before trusting any cron: trigger each service manually once from the
   Railway dashboard (confirm new listings land with `source =
   'zillow_email'` for the daily job, a digest email arrives for the
   weekly job, and RentCast rows update with `source = 'rentcast'` for the
   run-rentcast job), then monitor the first couple of scheduled runs.

## Tests

```bash
pytest
```

Tests run against recorded fixtures in `tests/fixtures/` — never against
live Gmail/ArcGIS/Anthropic APIs. `tests/fixtures/zillow_alert_*.eml` are
real (personally-received) Zillow alert emails, used to test
`canopy/clients/zillow_email.py`'s parser against real markup rather than
a hand-constructed guess.
