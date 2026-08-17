import os

from dotenv import load_dotenv

load_dotenv()


def _split_csv(raw: str) -> list[str]:
    return [z.strip() for z in raw.split(",") if z.strip()]


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

# Restored as a background-only weekly feed (canopy/cli.py::run_rentcast_weekly)
# after RentCast was fully retired as the primary listings source -- see
# docs/ARCHITECTURE.md's Appendix. RentCast-sourced listings never enter the
# rating queue; this exists purely to keep canopy/rentcast_backfill.py's
# collation data fresh.
RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "")

TARGET_ZIPS = _split_csv(
    os.environ.get("TARGET_ZIPS", "28403,28405,28409,28412,28428,28449")
)

# RentCast free tier is 50 calls/month. One call-batch per zip, run every
# ~5 days (canopy/cli.py::run_rentcast_weekly): 6 zips x ~6 runs/month =~
# 36 calls, comfortable headroom. Daily or every-72-hours would exceed the
# free tier. Same constraint as before RentCast's primary-source
# retirement, just lower stakes now that nothing downstream depends on
# this data being complete.
RENTCAST_MONTHLY_CALL_BUDGET = 50

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://canopy:canopy@localhost:5433/canopy"
)
# Some hosted Postgres providers (historically Heroku; possibly Railway)
# inject the legacy "postgres://" scheme, which SQLAlchemy 2.0 rejects.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
# Dual-purpose: SMTP send for the weekly digest (canopy/digest.py) AND IMAP
# login for polling Zillow alert emails (canopy/clients/gmail.py). A Gmail
# App Password works for both -- no separate credential needed.
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
DIGEST_TO_EMAIL = os.environ.get("DIGEST_TO_EMAIL", "")

# The Gmail label a filter routes incoming Zillow alert emails into (see
# README's setup steps). canopy/clients/gmail.py polls only this label, so
# ingestion never touches the rest of the inbox.
GMAIL_IMAP_LABEL = os.environ.get("GMAIL_IMAP_LABEL", "canopy-listings")

# Property types Zach and Andrea will never buy, stated as a hard
# constraint -- not a soft preference to learn nuance around (see
# SCORING_MODEL.md's hygiene/delighter/linear classification, which is
# for exactly that kind of nuance). Distinct from the retired hard filter:
# this scopes what counts as a candidate at all, the same way "for sale"
# vs. "for rent" already scopes the listing source, rather than
# eliminating candidates based on an uncertain threshold. Zillow's alert
# emails don't state an explicit property-type field at all (confirmed
# against real samples, canopy/clients/zillow_email.py's module docstring)
# -- so this branch of is_hard_excluded simply never fires for
# email-sourced listings today. Left in place (dormant, not removed) in
# case a future source or parser enhancement can populate property_type.
EXCLUDED_PROPERTY_TYPES = _split_csv(os.environ.get("EXCLUDED_PROPERTY_TYPES", "Condo,Apartment"))
