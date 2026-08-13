"""Stage 3: rating capture business logic -- judgments, comparisons,
anchors, and the batch/pair selection that feeds the rating UI. No Flask
here (canopy/api.py is the thin HTTP layer on top); this module is a
trust boundary in its own right, since judgments now come from an HTTP
client instead of a script we wrote ourselves."""

import logging
import math
import random
import re

from sqlalchemy.orm import Session

from canopy.clients.mapbox import geocode_address
from canopy.config import EXCLUDED_PROPERTY_TYPES
from canopy.db.models import (
    Anchor,
    Judgment,
    JudgmentAnchor,
    JudgmentTag,
    Listing,
    ListingAnchorTime,
    ListingFeatures,
    ModelRun,
    PairwiseComparison,
    PreferenceScore,
    Tag,
)
from canopy.features import FEATURE_SET_VERSION

logger = logging.getLogger(__name__)

VALID_MODES = {"swipe", "detail"}
VALID_VERDICTS = {"yes", "no", "maybe"}
EARTH_RADIUS_KM = 6371.0088
# Rough Wilmington-arterial-speed constant for the haversine drive-time
# proxy -- tune once real routing data exists. Every ListingAnchorTime row
# computed this way is stamped is_proxy=True so a later routing backfill
# is unambiguous.
KM_PER_MINUTE_PROXY = 0.55
VALID_WINNERS = {"a", "b", "tie"}
FREE_TEXT_TAG_CODES = {"other_yes", "other_no"}

# Features stratified across for a cold-start batch, per SCORING_MODEL.md
# §7 -- covers the whole market instead of clustering around whatever's
# cheapest to compute first. fronting_road_class is deferred (OSM
# integration not built yet) but listed here so this list doesn't need
# revisiting once it lands.
STRATIFY_FEATURES = ["parcel_canopy_pct", "lot_acreage", "list_price"]


class RatingValidationError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Judgments & comparisons
# ---------------------------------------------------------------------------


def record_judgment(
    session: Session,
    *,
    rater_id: str,
    listing_id: str,
    mode: str,
    verdict: str,
    session_id: str,
    tags: list[str] | None = None,
    anchor_ids: list[int] | None = None,
    free_text: str | None = None,
) -> Judgment:
    tags = tags or []
    anchor_ids = anchor_ids or []

    if mode not in VALID_MODES:
        raise RatingValidationError(f"invalid mode: {mode!r}")
    if verdict not in VALID_VERDICTS:
        raise RatingValidationError(f"invalid verdict: {verdict!r}")

    if verdict == "maybe":
        # low-information label; tagging would push people to yes/no for
        # the wrong reason (UI_SPEC.md §6) -- enforced server-side too
        if tags or anchor_ids:
            raise RatingValidationError("'maybe' verdicts cannot carry tags or anchor attribution")
    elif tags:
        expected_polarity = "positive" if verdict == "yes" else "negative"
        tag_rows = {t.code: t for t in session.query(Tag).filter(Tag.code.in_(tags)).all()}
        missing = set(tags) - set(tag_rows)
        if missing:
            raise RatingValidationError(f"unknown tag codes: {sorted(missing)}")
        mismatched = [code for code, t in tag_rows.items() if t.polarity != expected_polarity]
        if mismatched:
            raise RatingValidationError(
                f"tags don't match verdict polarity ({verdict}): {sorted(mismatched)}"
            )

    judgment = Judgment(
        rater_id=rater_id, listing_id=listing_id, mode=mode, verdict=verdict,
        session_id=session_id, feature_set_version=FEATURE_SET_VERSION,
    )
    session.add(judgment)
    session.flush()  # assigns judgment.id without committing yet

    for tag_code in tags:
        session.add(JudgmentTag(
            judgment_id=judgment.id, tag_code=tag_code,
            free_text=free_text if tag_code in FREE_TEXT_TAG_CODES else None,
        ))
    for anchor_id in anchor_ids:
        session.add(JudgmentAnchor(judgment_id=judgment.id, anchor_id=anchor_id))

    session.commit()
    logger.info("judgment %s: rater=%s listing=%s verdict=%s tags=%s", judgment.id, rater_id, listing_id, verdict, tags)
    return judgment


def record_comparison(
    session: Session,
    *,
    rater_id: str,
    listing_a: str,
    listing_b: str,
    winner: str,
    selection_strategy: str | None = None,
) -> PairwiseComparison:
    if winner not in VALID_WINNERS:
        raise RatingValidationError(f"invalid winner: {winner!r}")

    comparison = PairwiseComparison(
        rater_id=rater_id, listing_a=listing_a, listing_b=listing_b, winner=winner,
        selection_strategy=selection_strategy, feature_set_version=FEATURE_SET_VERSION,
    )
    session.add(comparison)
    session.commit()
    logger.info("comparison %s: rater=%s a=%s b=%s winner=%s", comparison.id, rater_id, listing_a, listing_b, winner)
    return comparison


# ---------------------------------------------------------------------------
# Batch / pair selection
# ---------------------------------------------------------------------------


def _stratified_sample(candidates: list[ListingFeatures], n: int) -> list[ListingFeatures]:
    """Buckets candidates into terciles per STRATIFY_FEATURES and samples
    roughly evenly across buckets, so an early batch covers the space
    instead of clustering around whatever's cheapest to compute first."""
    if len(candidates) <= n:
        return list(candidates)

    def make_bucket_fn(attr: str):
        values = sorted(v for r in candidates if (v := getattr(r, attr)) is not None)
        if len(values) < 3:
            return lambda row: 0
        t1, t2 = values[len(values) // 3], values[2 * len(values) // 3]

        def bucket(row):
            v = getattr(row, attr)
            if v is None:
                return -1
            return 0 if v <= t1 else (1 if v <= t2 else 2)

        return bucket

    bucket_fns = [make_bucket_fn(f) for f in STRATIFY_FEATURES]
    buckets: dict[tuple, list[ListingFeatures]] = {}
    for row in candidates:
        key = tuple(fn(row) for fn in bucket_fns)
        buckets.setdefault(key, []).append(row)

    rng = random.Random()
    per_bucket = max(1, n // max(len(buckets), 1))
    sample: list[ListingFeatures] = []
    for rows in buckets.values():
        rng.shuffle(rows)
        sample.extend(rows[:per_bucket])

    if len(sample) < n:
        chosen_ids = {row.listing_id for row in sample}
        remaining = [row for row in candidates if row.listing_id not in chosen_ids]
        rng.shuffle(remaining)
        sample.extend(remaining[: n - len(sample)])

    rng.shuffle(sample)
    return sample[:n]


def _latest_model_run(session: Session, rater_id: str) -> ModelRun | None:
    return (
        session.query(ModelRun)
        .filter(ModelRun.rater_id == rater_id)
        .order_by(ModelRun.trained_at.desc())
        .first()
    )


def _listings_for(session: Session, listing_ids: list[str]) -> list[Listing]:
    rows = session.query(Listing).filter(Listing.id.in_(listing_ids)).all()
    by_id = {row.id: row for row in rows}
    return [by_id[lid] for lid in listing_ids if lid in by_id]


# Matches "7401-7429 Starlight Ln" (house-number range), "109 And 113
# Clay St" / "636 And 644 S Third Ave" ("X And Y" combined addresses),
# and "Lot 1-2" (multi-lot assemblage) -- verified against all 1028 real
# ingested listings: exactly 5 matches, all genuine multi-parcel
# listings, zero false positives. A listing spanning multiple house
# numbers or lots isn't a single buildable homesite by definition, same
# category of hard-no as EXCLUDED_PROPERTY_TYPES (not a soft threshold
# to learn nuance around).
MULTI_ADDRESS_PATTERN = re.compile(r"^\d+-\d+|\band\s+\d+|lot\s+\d+-\d+", re.IGNORECASE)


def is_hard_excluded(property_type: str | None, formatted_address: str | None) -> bool:
    """A listing is never a candidate at all -- not ranked low, never
    shown -- if it's a stated hard-no property type (Condo/Apartment) or
    an address spanning multiple house numbers/lots (not a single
    buildable homesite). See CLAUDE.md's constraint list for why this is
    distinct from the retired rank-vs-eliminate hard filter."""
    if property_type in EXCLUDED_PROPERTY_TYPES:
        return True
    if formatted_address and MULTI_ADDRESS_PATTERN.search(formatted_address):
        return True
    return False


def excluded_listing_ids(session: Session) -> set[str]:
    """Enforced here (not just in cli.py's pipeline) so listings
    featured/scored before an exclusion was added still can't surface as
    rating candidates without a data migration."""
    rows = session.query(Listing.id, Listing.property_type, Listing.formatted_address)
    return {listing_id for listing_id, property_type, address in rows if is_hard_excluded(property_type, address)}


def get_batch(session: Session, rater_id: str, n: int = 40) -> list[Listing]:
    judged_ids = {
        listing_id for (listing_id,) in
        session.query(Judgment.listing_id).filter(Judgment.rater_id == rater_id)
    }
    excluded_ids = excluded_listing_ids(session)
    candidates = (
        session.query(ListingFeatures)
        .filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
        .filter(~ListingFeatures.listing_id.in_(judged_ids))
        .filter(~ListingFeatures.listing_id.in_(excluded_ids))
        .all()
    )

    latest_run = _latest_model_run(session, rater_id)
    if latest_run is None:
        chosen = _stratified_sample(candidates, n)
    else:
        variance_by_listing = {
            ps.listing_id: ps.pred_variance for ps in
            session.query(PreferenceScore).filter(PreferenceScore.model_run_id == latest_run.id)
        }
        chosen = sorted(
            candidates, key=lambda row: variance_by_listing.get(row.listing_id) or -1, reverse=True
        )[:n]

    return _listings_for(session, [row.listing_id for row in chosen])


def _random_pair(session: Session) -> tuple[Listing, Listing]:
    excluded_ids = excluded_listing_ids(session)
    ids = [
        row[0] for row in
        session.query(ListingFeatures.listing_id)
        .filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
        .filter(~ListingFeatures.listing_id.in_(excluded_ids))
        .all()
    ]
    if len(ids) < 2:
        raise RatingValidationError("not enough listings with computed features for a comparison pair")
    a_id, b_id = random.sample(ids, 2)
    listings = _listings_for(session, [a_id, b_id])
    return listings[0], listings[1]


def get_pair(session: Session, rater_id: str) -> tuple[Listing, Listing, str]:
    """Cold-start: random pair. Post-cold-start: active selection --
    smallest predicted-score gap (P ≈ 0.5), tie-broken toward higher
    combined pred_variance (bootstrap disagreement), per SCORING_MODEL.md
    §6. Reads PreferenceScore rows already written by canopy/model.py's
    score_listings -- doesn't need to import the model itself."""
    latest_run = _latest_model_run(session, rater_id)
    if latest_run is None:
        listing_a, listing_b = _random_pair(session)
        return listing_a, listing_b, "random"

    excluded_ids = excluded_listing_ids(session)
    scores = (
        session.query(PreferenceScore)
        .filter(PreferenceScore.model_run_id == latest_run.id)
        .filter(~PreferenceScore.listing_id.in_(excluded_ids))
        .order_by(PreferenceScore.raw_score)
        .all()
    )
    if len(scores) < 2:
        listing_a, listing_b = _random_pair(session)
        return listing_a, listing_b, "random"

    best_pair = None
    best_key = None
    for a, b in zip(scores, scores[1:]):
        gap = abs(a.raw_score - b.raw_score)
        variance = (a.pred_variance or 0) + (b.pred_variance or 0)
        key = (gap, -variance)
        if best_key is None or key < best_key:
            best_key, best_pair = key, (a, b)

    listings = _listings_for(session, [best_pair[0].listing_id, best_pair[1].listing_id])
    return listings[0], listings[1], "active"


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------


def create_anchor(
    session: Session,
    *,
    label: str,
    category: str,
    created_by: str,
    lat: float | None = None,
    lon: float | None = None,
    address: str | None = None,
    ideal_minutes: int = 15,
    limit_minutes: int = 30,
) -> Anchor:
    resolved_address = None
    if lat is None or lon is None:
        if not address:
            raise RatingValidationError("must provide either lat/lon or an address to geocode")
        geocoded = geocode_address(address)
        if geocoded is None:
            raise RatingValidationError(f"could not geocode address: {address!r}")
        lat, lon, resolved_address = geocoded

    anchor = Anchor(
        label=label, category=category, lat=lat, lon=lon, resolved_address=resolved_address,
        ideal_minutes=ideal_minutes, limit_minutes=limit_minutes, created_by=created_by,
    )
    session.add(anchor)
    session.commit()
    return anchor


def update_anchor(session: Session, anchor_id: int, **fields) -> Anchor:
    anchor = session.get(Anchor, anchor_id)
    if anchor is None:
        raise RatingValidationError(f"anchor {anchor_id} not found")
    for key in ("label", "category", "ideal_minutes", "limit_minutes", "active"):
        if key in fields and fields[key] is not None:
            setattr(anchor, key, fields[key])
    session.commit()
    return anchor


def delete_anchor(session: Session, anchor_id: int) -> None:
    anchor = session.get(Anchor, anchor_id)
    if anchor is None:
        raise RatingValidationError(f"anchor {anchor_id} not found")
    anchor.active = False  # soft delete -- past judgments still reference it
    session.commit()


def list_anchors(session: Session, include_inactive: bool = False) -> list[Anchor]:
    query = session.query(Anchor)
    if not include_inactive:
        query = query.filter(Anchor.active.is_(True))
    return query.order_by(Anchor.label).all()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def ensure_anchor_times(session: Session, listing: Listing) -> dict[int, ListingAnchorTime]:
    """Haversine-proxy drive times from a listing to every active anchor,
    computed once per (listing, anchor) pair and cached -- same lazy
    pattern as canopy/vision.py. Real routing (deferred) would backfill
    these rows in place later, flipping is_proxy to False; no schema
    change needed then."""
    anchors = list_anchors(session)
    existing = {
        row.anchor_id: row for row in
        session.query(ListingAnchorTime).filter_by(listing_id=listing.id)
    }
    for anchor in anchors:
        if anchor.id in existing:
            continue
        straight_line_km = _haversine_km(listing.latitude, listing.longitude, anchor.lat, anchor.lon)
        row = ListingAnchorTime(
            listing_id=listing.id, anchor_id=anchor.id,
            drive_minutes=straight_line_km / KM_PER_MINUTE_PROXY,
            straight_line_km=straight_line_km, is_proxy=True,
        )
        session.add(row)
        existing[anchor.id] = row
    if anchors:
        session.commit()
    return existing
