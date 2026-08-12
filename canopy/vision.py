"""Lazy vision pass -- structural/architecture feature extraction +
rationale synthesis, called on first view of a listing (from the rating
API, canopy/api.py) rather than as a weekly bulk step.

Once the hard filter is retired, every listing can be viewed by a rater at
any time -- not just a short pre-filtered list -- so running Claude vision
on the full weekly volume would blow past this project's cost discipline
(docs/CLAUDE.md). This runs once per listing instead, on demand, and is
cached via ListingFeatures.vision_computed_at.

This replaces canopy/subagent.py's old "Stage 5, filtered candidates only"
role; subagent.py itself is retired in the Stage 6 cutover once cli.py
stops calling it in bulk."""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from canopy.clients.anthropic_client import extract_structural_features
from canopy.clients.mapbox import fetch_satellite_image
from canopy.db.models import Listing, ListingFeatures, Parcel, Score

logger = logging.getLogger(__name__)


def _structured_facts(
    listing: Listing, parcel: Parcel | None, score: Score | None, features: ListingFeatures
) -> dict:
    return {
        "address": listing.formatted_address,
        "price": listing.price,
        "lot_acreage": features.lot_acreage,
        "protected_perimeter_ratio": features.protected_perimeter_ratio,
        "abuts_water": features.abuts_water,
        "abuts_marsh_wetland": features.abuts_marsh_wetland,
        "abuts_park_public": features.abuts_park_public,
        "abuts_conservation_easement": features.abuts_conservation_easement,
        "abuts_buildable_private": features.abuts_buildable_private,
        "parcel_canopy_pct": features.parcel_canopy_pct,
        "neighborhood_canopy_pct": features.neighborhood_canopy_pct,
        "flood_zone": features.flood_zone,
        "year_built": listing.year_built,
    }


def ensure_vision_features(session: Session, listing: Listing, features: ListingFeatures) -> ListingFeatures:
    """Idempotent -- does nothing if this listing's vision pass already ran
    for the current feature set. Takes the already-computed ListingFeatures
    row (canopy/features.py) so this never re-derives deterministic
    signals; it only adds the parts that genuinely need vision."""
    if features.vision_computed_at is not None:
        return features

    parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
    score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()

    image_bytes = fetch_satellite_image(listing.latitude, listing.longitude)
    facts = _structured_facts(listing, parcel, score, features)
    result = extract_structural_features(facts, image_bytes)

    features.arch_style = result["arch_style"]
    features.arch_style_confidence = result["arch_style_confidence"]
    features.exterior_material = result["exterior_material"]
    features.has_front_porch = result["has_front_porch"]
    features.garage_type = result["garage_type"]
    features.visible_renovation_recency = result["visible_renovation_recency"]
    features.vision_computed_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    rationale = result["rationale"]
    if result.get("concerns"):
        rationale = f"{rationale} (Note: {result['concerns']})"
    if score is not None:
        score.subagent_rationale = rationale

    session.commit()
    logger.info("vision %s: arch_style=%s rationale=%s", listing.id, features.arch_style, rationale)
    return features
