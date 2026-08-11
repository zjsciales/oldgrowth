import os

from dotenv import load_dotenv

load_dotenv()


def _split_zips(raw: str) -> list[str]:
    return [z.strip() for z in raw.split(",") if z.strip()]


RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MAPBOX_API_KEY = os.environ.get("MAPBOX_API_KEY", "")

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://canopy:canopy@localhost:5433/canopy"
)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
DIGEST_TO_EMAIL = os.environ.get("DIGEST_TO_EMAIL", "")

TARGET_ZIPS = _split_zips(
    os.environ.get("TARGET_ZIPS", "28403,28405,28409,28412,28428,28449")
)

# RentCast free tier is 50 calls/month. One call-batch per zip per weekly
# run keeps ~6 zips x ~4.3 weeks/month well under budget with headroom.
RENTCAST_MONTHLY_CALL_BUDGET = 50

# Stage 4 rule-based filter thresholds. Conservative defaults so the first
# few runs don't come back empty; tune after seeing real output.
MIN_LOT_SIZE_SQFT = int(os.environ.get("MIN_LOT_SIZE_SQFT", "15000"))
MIN_CANOPY_PCT = float(os.environ.get("MIN_CANOPY_PCT", "40"))
REQUIRE_ADJACENCY_FLAG = os.environ.get("REQUIRE_ADJACENCY_FLAG", "true").lower() == "true"
