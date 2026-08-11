"""Stage 4: rule-based filter over scored listings. Deterministic,
config-driven thresholds per docs/CLAUDE.md -- produces the short candidate
list that goes on to the (expensive) Stage 5 Claude sub-agent."""

import logging

from sqlalchemy.orm import Session

from canopy.config import MIN_CANOPY_PCT, MIN_LOT_SIZE_SQFT, REQUIRE_ADJACENCY_FLAG
from canopy.db.models import Listing, Parcel, Score

logger = logging.getLogger(__name__)


def evaluate_listing(listing: Listing, parcel: Parcel | None, score: Score) -> tuple[bool, dict]:
    """Returns (passed, reasons) where reasons documents why each check
    passed/failed -- stored alongside the result for auditability."""
    reasons: dict[str, bool] = {}

    reasons["lot_size_ok"] = (
        listing.lot_size_sqft is not None and listing.lot_size_sqft >= MIN_LOT_SIZE_SQFT
    )
    reasons["canopy_pct_ok"] = (
        score.canopy_pct is not None and score.canopy_pct >= MIN_CANOPY_PCT
    )

    has_adjacency_flag = bool(
        parcel is not None
        and (
            parcel.adjacent_water
            or parcel.adjacent_park_or_conservation
            or parcel.adjacent_county_or_city_owned
            or parcel.wetland_overlay
        )
    )
    reasons["adjacency_ok"] = has_adjacency_flag if REQUIRE_ADJACENCY_FLAG else True

    passed = all(reasons.values())
    return passed, reasons


def filter_listings(session: Session, listings: list[Listing]) -> list[Listing]:
    """Applies the rule-based filter to each listing's existing Score record
    (must already be populated by Stage 3) and returns the candidates that
    passed -- the short list that Stage 5 will spend AI budget on."""
    candidates: list[Listing] = []

    for listing in listings:
        parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
        score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()
        if score is None:
            logger.warning("skipping %s: not yet scored", listing.id)
            continue

        passed, reasons = evaluate_listing(listing, parcel, score)
        score.passed_filter = passed
        score.filter_reasons = reasons

        if passed:
            candidates.append(listing)

        logger.info("filter %s: passed=%s reasons=%s", listing.id, passed, reasons)

    session.commit()
    return candidates
