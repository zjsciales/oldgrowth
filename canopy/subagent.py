"""Stage 5: Claude sub-agent -- vision sanity-check + rationale synthesis,
applied only to the short candidate list that already passed Stage 4."""

import logging

from sqlalchemy.orm import Session

from canopy.clients.anthropic_client import evaluate_candidate
from canopy.clients.mapbox import fetch_satellite_image
from canopy.db.models import Listing, Parcel, Score

logger = logging.getLogger(__name__)


def _structured_facts(listing: Listing, parcel: Parcel | None, score: Score) -> dict:
    return {
        "address": listing.formatted_address,
        "price": listing.price,
        "lot_size_sqft": listing.lot_size_sqft,
        "year_built": listing.year_built,
        "canopy_pct": score.canopy_pct,
        "old_growth_proxy_score": score.old_growth_proxy_score,
        "adjacent_water": parcel.adjacent_water if parcel else None,
        "adjacent_park_or_conservation": parcel.adjacent_park_or_conservation if parcel else None,
        "adjacent_county_or_city_owned": parcel.adjacent_county_or_city_owned if parcel else None,
        "flood_zone": parcel.flood_zone if parcel else None,
        "wetland_overlay": parcel.wetland_overlay if parcel else None,
    }


def run_subagent_on_candidates(session: Session, candidates: list[Listing]) -> list[Score]:
    results: list[Score] = []

    for listing in candidates:
        parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
        score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()
        if score is None:
            logger.warning("skipping subagent for %s: not yet scored", listing.id)
            continue

        image_bytes = fetch_satellite_image(listing.latitude, listing.longitude)
        facts = _structured_facts(listing, parcel, score)
        result = evaluate_candidate(facts, image_bytes)

        score.subagent_flag_ok = result["flag_ok"]
        rationale = result["rationale"]
        if result.get("concerns"):
            rationale = f"{rationale} (Note: {result['concerns']})"
        score.subagent_rationale = rationale

        session.commit()  # per-candidate, so a mid-run failure doesn't lose already-billed calls
        results.append(score)
        logger.info(
            "subagent %s: flag_ok=%s rationale=%s",
            listing.id, score.subagent_flag_ok, score.subagent_rationale,
        )

    return results
