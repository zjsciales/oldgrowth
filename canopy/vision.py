"""Lazy vision pass -- structural/architecture feature extraction,
rationale/summary synthesis, and a canopy-condition check against the
(potentially stale) NLCD raster, called on first view of a listing (from
the rating API, canopy/api.py) rather than as a weekly bulk step.

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

import requests
from sqlalchemy.orm import Session

from canopy.clients.anthropic_client import extract_structural_features
from canopy.clients.mapbox import fetch_satellite_image
from canopy.db.models import Listing, ListingFeatures, Parcel, Score
from canopy.features import compute_canopy_delta

logger = logging.getLogger(__name__)

# canopy_condition_confidence must clear this before a vision read is
# allowed to change effective_canopy_pct (a real trained ranking input,
# canopy/model.py) -- this directly changes what the model learns from, so
# start conservative; revisit after seeing real vision-vs-raster agreement
# rates across a batch of listings.
CANOPY_OVERRIDE_CONFIDENCE_THRESHOLD = 0.75

LISTING_PHOTO_FETCH_TIMEOUT_SECONDS = 10


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


def _fetch_listing_photo_bytes(photo_url: str) -> bytes | None:
    """Best-effort fetch of Listing.photo_url's bytes to feed alongside the
    Mapbox satellite image in the same vision call. Never raises -- a
    fetch failure falls back to satellite-only, same as a missing
    photo_url."""
    try:
        resp = requests.get(photo_url, timeout=LISTING_PHOTO_FETCH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException:
        logger.warning("failed to fetch listing photo for vision pass: %s", photo_url)
        return None


def ensure_vision_features(session: Session, listing: Listing, features: ListingFeatures) -> ListingFeatures:
    """Idempotent -- does nothing if this listing's vision pass already ran
    for the current feature set. Takes the already-computed ListingFeatures
    row (canopy/features.py) so this never re-derives deterministic
    signals; it only adds the parts that genuinely need vision."""
    if features.vision_computed_at is not None:
        return features
    if listing.latitude is None or listing.longitude is None:
        # No coordinates to fetch satellite imagery for (email-sourced
        # address that never geocoded) -- leave vision fields null, same
        # as any other imputed field, rather than crashing the batch/pair
        # request that triggered this.
        return features

    parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
    score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()

    image_bytes = fetch_satellite_image(listing.latitude, listing.longitude)
    listing_photo_bytes = _fetch_listing_photo_bytes(listing.photo_url) if listing.photo_url else None
    facts = _structured_facts(listing, parcel, score, features)
    result = extract_structural_features(facts, image_bytes, listing_photo_bytes)

    features.arch_style = result["arch_style"]
    features.arch_style_confidence = result["arch_style_confidence"]
    features.exterior_material = result["exterior_material"]
    features.has_front_porch = result["has_front_porch"]
    features.garage_type = result["garage_type"]
    features.visible_renovation_recency = result["visible_renovation_recency"]
    features.vision_computed_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

    features.house_lot_summary = result["house_lot_summary"]
    features.canopy_condition = result["canopy_condition"]
    features.canopy_condition_confidence = result["canopy_condition_confidence"]
    features.vision_canopy_pct_estimate = result["corrected_canopy_pct_estimate"]

    should_override = (
        result["canopy_condition"] in ("recently_cleared", "significant_regrowth")
        and result["canopy_condition_confidence"] >= CANOPY_OVERRIDE_CONFIDENCE_THRESHOLD
    )
    if should_override:
        features.effective_canopy_pct = result["corrected_canopy_pct_estimate"]
        features.canopy_pct_overridden_by_vision = True
        # canopy_delta (neighborhood - lot) is itself a real trained
        # feature (canopy/model.py) -- if it stayed computed from the
        # stale raster value, the feature vector would be internally
        # inconsistent with effective_canopy_pct, reintroducing the exact
        # staleness this override exists to fix.
        features.canopy_delta = compute_canopy_delta(features.neighborhood_canopy_pct, features.effective_canopy_pct)

    rationale = result["rationale"]
    if result.get("concerns"):
        rationale = f"{rationale} (Note: {result['concerns']})"
    if score is not None:
        score.subagent_rationale = rationale

    session.commit()
    logger.info(
        "vision %s: arch_style=%s canopy_condition=%s (confidence=%.2f, overridden=%s) rationale=%s",
        listing.id, features.arch_style, result["canopy_condition"],
        result["canopy_condition_confidence"], should_override, rationale,
    )
    return features
