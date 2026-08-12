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

python -m canopy.cli run-weekly --dry-run   # dry-run: skips sending email, logs digest HTML instead
python -m canopy.cli run-weekly             # live run: ingest, enrich, score, compute features, refit both raters' models, email digest
```

For active frontend iteration, run `flask run --port 5000` (no PORT
override — `frontend/vite.config.js`'s dev proxy targets `127.0.0.1:5000`
explicitly) in one terminal and `npm run dev --prefix frontend` in
another; the Vite dev server proxies `/api/*` to Flask.

## Deploy (Railway)

`nixpacks.toml` runs a Node build phase (`npm --prefix frontend ci && npm
--prefix frontend run build`) ahead of the Python install/start, so
`canopy/static/dist/` exists before `gunicorn canopy.app:app` serves `/`.
Not yet run for real — see below.

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
7. This first deploy is also intentionally where the full 1023-listing
   backlog (`compute-features` etc.) should run for real, once the
   Postgres plugin is set up — not locally first (standing decision, see
   `docs/ARCHITECTURE.md`).

## Tests

```bash
pytest
```

Tests run against recorded fixtures in `tests/fixtures/` — never against
live RentCast/ArcGIS/Anthropic APIs (RentCast's free tier is capped at
50 calls/month).
