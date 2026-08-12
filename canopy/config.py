import os

from dotenv import load_dotenv

load_dotenv()


def _split_csv(raw: str) -> list[str]:
    return [z.strip() for z in raw.split(",") if z.strip()]


RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://canopy:canopy@localhost:5433/canopy"
)
# Some hosted Postgres providers (historically Heroku; possibly Railway)
# inject the legacy "postgres://" scheme, which SQLAlchemy 2.0 rejects.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
DIGEST_TO_EMAIL = os.environ.get("DIGEST_TO_EMAIL", "")

TARGET_ZIPS = _split_csv(
    os.environ.get("TARGET_ZIPS", "28403,28405,28409,28412,28428,28449")
)

# RentCast free tier is 50 calls/month. One call-batch per zip per weekly
# run keeps ~6 zips x ~4.3 weeks/month well under budget with headroom.
RENTCAST_MONTHLY_CALL_BUDGET = 50

# Property types Zach and Andrea will never buy, stated as a hard
# constraint -- not a soft preference to learn nuance around (see
# SCORING_MODEL.md's hygiene/delighter/linear classification, which is
# for exactly that kind of nuance). Distinct from the retired hard filter:
# this scopes what counts as a candidate at all, the same way "for sale"
# vs. "for rent" already scopes the RentCast query, rather than
# eliminating candidates based on an uncertain threshold. Values must
# match RentCast's `propertyType` field exactly (verified against real
# ingested data: "Single Family", "Townhouse", "Condo", "Land",
# "Multi-Family", "Manufactured" all appear; "Apartment" does not appear
# in this market's sale listings but is excluded defensively).
EXCLUDED_PROPERTY_TYPES = _split_csv(os.environ.get("EXCLUDED_PROPERTY_TYPES", "Condo,Apartment"))
