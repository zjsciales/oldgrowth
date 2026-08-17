"""Stage 3 JSON API -- thin HTTP layer over canopy/rating.py. No business
logic lives here; this parses requests, calls into rating.py/vision.py,
and serializes responses. See docs/UI_SPEC.md §5 for the contract."""

import logging
import uuid

from flask import Blueprint, Response, jsonify, request

from canopy.clients.mapbox import MapboxError, fetch_location_map
from canopy.config import TARGET_ZIPS
from canopy.db.models import Anchor, Listing, ListingFeatures, ModelRun, Parcel, Tag
from canopy.db.session import SessionLocal
from canopy.features import FEATURE_SET_VERSION
from canopy.listing_links import NHC_RECORDS_SEARCH_URL, listing_search_url, satellite_url
from canopy.model import classify_features_from_tags
from canopy.rating import (
    RatingValidationError,
    create_anchor,
    delete_anchor,
    ensure_anchor_times,
    get_batch,
    get_pair,
    list_anchors,
    record_comparison,
    record_judgment,
    update_anchor,
)
from canopy.vision import ensure_vision_features

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")

DEFAULT_EDGES = {"n": "buildable", "e": "buildable", "s": "buildable", "w": "buildable"}

# A batch can contain listings that have never had a vision pass; each one
# is a synchronous Anthropic + Mapbox round-trip (each individually bounded
# by its own client timeout -- see anthropic_client.REQUEST_TIMEOUT_SECONDS
# and mapbox.py's fetch_satellite_image -- but still real wall-clock time
# on the happy path). Uncapped, a batch full of never-viewed listings (e.g.
# right after a fresh ingest) can blow past gunicorn's worker timeout and
# take the worker down. Capping keeps every batch response fast; listings
# past the cap simply render without vision-derived fields until a later
# view processes them.
MAX_VISION_CALLS_PER_BATCH = 3


def _features_for(session, listing: Listing) -> ListingFeatures | None:
    return (
        session.query(ListingFeatures)
        .filter_by(listing_id=listing.id, feature_set_version=FEATURE_SET_VERSION)
        .one_or_none()
    )


def _try_ensure_vision(session, listing: Listing, features: ListingFeatures) -> None:
    """Vision is an enhancement (architecture tags + rationale), not a
    requirement for a listing card to render -- a Mapbox/Anthropic hiccup
    on one listing shouldn't 500 the whole batch/pair response."""
    try:
        ensure_vision_features(session, listing, features)
    except Exception:
        logger.exception("vision pass failed for %s, continuing without it", listing.id)


def _listing_card(session, listing: Listing, features: ListingFeatures) -> dict:
    anchor_times = ensure_anchor_times(session, listing)
    anchors_by_id = {a.id: a for a in list_anchors(session)}
    drives = {
        anchors_by_id[anchor_id].label: round(row.drive_minutes)
        for anchor_id, row in anchor_times.items()
        if anchor_id in anchors_by_id and row.drive_minutes is not None
    }
    edges = (features.extra or {}).get("edges") or DEFAULT_EDGES
    parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()

    return {
        "id": listing.id,
        "address": listing.formatted_address,
        "price": listing.price,
        "searchUrl": listing_search_url(listing.formatted_address),
        "satelliteUrl": satellite_url(listing.latitude, listing.longitude),
        "countyRecordsUrl": NHC_RECORDS_SEARCH_URL,
        "parcelId": parcel.parcel_id if parcel else None,
        "photoUrl": listing.photo_url,
        "collatedWithRentcast": listing.collated_with_rentcast,
        "outOfArea": bool(listing.zip_code) and listing.zip_code not in TARGET_ZIPS,
        "sqft": features.sqft,
        "beds": features.beds,
        "baths": features.baths,
        "yearBuilt": features.year_built,
        "lotAcres": round(features.lot_acreage, 2) if features.lot_acreage is not None else None,
        "parcelCanopy": round(features.parcel_canopy_pct) if features.parcel_canopy_pct is not None else None,
        "neighborhoodCanopy": (
            round(features.neighborhood_canopy_pct) if features.neighborhood_canopy_pct is not None else None
        ),
        "protectedRatio": features.protected_perimeter_ratio,
        "roadClass": features.fronting_road_class,  # null until OSM integration (deferred)
        "isCulDeSac": features.is_cul_de_sac,
        "floodZone": features.flood_zone,
        "archStyle": features.arch_style,
        "isTractNewBuild": features.is_tract_new_build,
        "dom": features.days_on_market,
        "rearOpenFt": features.rear_open_distance_ft,
        "drives": drives,
        "edges": edges,
    }


def _anchor_json(anchor: Anchor) -> dict:
    return {
        "id": anchor.id, "label": anchor.label, "category": anchor.category,
        "lat": anchor.lat, "lon": anchor.lon, "resolvedAddress": anchor.resolved_address,
        "ideal": anchor.ideal_minutes, "limit": anchor.limit_minutes,
        "createdBy": anchor.created_by, "active": anchor.active,
    }


@api_bp.get("/listings/<listing_id>/location-map")
def location_map(listing_id):
    """Streets-style map + pin, ~1mi radius -- stands in for a listing
    photo (canopy/clients/mapbox.py's fetch_location_map docstring has
    the full "why not a real photo" context). A fixed lat/lon's map never
    changes, so this is safe to cache aggressively client-side rather
    than re-fetching from Mapbox on every view."""
    session = SessionLocal()
    try:
        listing = session.get(Listing, listing_id)
        if listing is None:
            return jsonify(error="listing not found"), 404
        if listing.latitude is None or listing.longitude is None:
            return jsonify(error="location unknown for this listing"), 404
        try:
            image_bytes = fetch_location_map(listing.latitude, listing.longitude)
        except MapboxError as exc:
            return jsonify(error=str(exc)), 502
        return Response(image_bytes, mimetype="image/png", headers={
            "Cache-Control": "public, max-age=31536000, immutable",
        })
    finally:
        session.close()


@api_bp.get("/batch")
def batch():
    rater_id = request.args.get("rater")
    if not rater_id:
        return jsonify(error="rater is required"), 400
    n = request.args.get("n", default=40, type=int)

    session = SessionLocal()
    try:
        listings = get_batch(session, rater_id, n=n)
        cards = []
        vision_calls = 0
        for listing in listings:
            features = _features_for(session, listing)
            if features is None:
                continue
            if features.vision_computed_at is None and vision_calls >= MAX_VISION_CALLS_PER_BATCH:
                cards.append(_listing_card(session, listing, features))
                continue
            if features.vision_computed_at is None:
                vision_calls += 1
            _try_ensure_vision(session, listing, features)
            cards.append(_listing_card(session, listing, features))
        return jsonify(listings=cards, batch_id=str(uuid.uuid4()))
    finally:
        session.close()


@api_bp.get("/pair")
def pair():
    rater_id = request.args.get("rater")
    if not rater_id:
        return jsonify(error="rater is required"), 400

    session = SessionLocal()
    try:
        listing_a, listing_b, strategy = get_pair(session, rater_id)
        features_a = _features_for(session, listing_a)
        features_b = _features_for(session, listing_b)
        if features_a is None or features_b is None:
            return jsonify(error="selected listings are missing computed features"), 500
        _try_ensure_vision(session, listing_a, features_a)
        _try_ensure_vision(session, listing_b, features_b)
        return jsonify(
            listing_a=_listing_card(session, listing_a, features_a),
            listing_b=_listing_card(session, listing_b, features_b),
            selection_strategy=strategy,
        )
    except RatingValidationError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        session.close()


@api_bp.post("/judgment")
def judgment():
    body = request.get_json(force=True, silent=True) or {}
    session = SessionLocal()
    try:
        result = record_judgment(
            session,
            rater_id=body.get("rater_id"),
            listing_id=body.get("listing_id"),
            mode=body.get("mode"),
            verdict=body.get("verdict"),
            session_id=body.get("session_id"),
            tags=body.get("tags"),
            anchor_ids=body.get("anchor_ids"),
            free_text=body.get("free_text"),
        )
        return jsonify(id=result.id), 201
    except RatingValidationError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        session.close()


@api_bp.post("/comparison")
def comparison():
    body = request.get_json(force=True, silent=True) or {}
    session = SessionLocal()
    try:
        result = record_comparison(
            session,
            rater_id=body.get("rater_id"),
            listing_a=body.get("listing_a"),
            listing_b=body.get("listing_b"),
            winner=body.get("winner"),
            selection_strategy=body.get("selection_strategy"),
        )
        return jsonify(id=result.id), 201
    except RatingValidationError as exc:
        return jsonify(error=str(exc)), 400
    finally:
        session.close()


@api_bp.get("/weights")
def weights():
    rater_id = request.args.get("rater")
    if not rater_id:
        return jsonify(error="rater is required"), 400

    session = SessionLocal()
    try:
        # credit/blame/kind per feature (SCORING_MODEL.md §4.1) -- doesn't
        # need a fitted model, just judgment_tags, so it's meaningful even
        # in the "not_enough_data" cold-start case (this is what powers
        # both the future weights dashboard and the Patterns tab preview)
        tag_stats = {
            name: {"credit": info["credit"], "blame": info["blame"], "n": info["n"], "kind": info["kind"]}
            for name, info in classify_features_from_tags(session, rater_id).items()
        }

        latest_run = (
            session.query(ModelRun)
            .filter(ModelRun.rater_id == rater_id)
            .order_by(ModelRun.trained_at.desc())
            .first()
        )
        if latest_run is None:
            return jsonify(status="not_enough_data", coefficients={}, n_pairs=0, tagStats=tag_stats)
        return jsonify(
            status="ok",
            n_pairs=latest_run.n_pairs,
            coefficients=latest_run.coefficients,
            coefCi=latest_run.coef_ci,
            basisConfig=latest_run.basis_config,
            holdoutAccuracy=latest_run.holdout_accuracy,
            baselineAccuracy=latest_run.baseline_accuracy,
            trainedAt=latest_run.trained_at.isoformat(),
            tagStats=tag_stats,
        )
    finally:
        session.close()


@api_bp.get("/tags")
def tags():
    session = SessionLocal()
    try:
        rows = session.query(Tag).filter(Tag.active.is_(True)).all()
        return jsonify(tags=[
            {
                "code": t.code, "label": t.label, "polarity": t.polarity,
                "mappedFeatures": t.mapped_features, "anchorAware": t.anchor_aware,
            }
            for t in rows
        ])
    finally:
        session.close()


@api_bp.get("/anchors")
def anchors_list():
    session = SessionLocal()
    try:
        return jsonify(anchors=[_anchor_json(a) for a in list_anchors(session)])
    finally:
        session.close()


@api_bp.post("/anchors")
def anchors_create():
    body = request.get_json(force=True, silent=True) or {}
    session = SessionLocal()
    try:
        anchor = create_anchor(
            session,
            label=body.get("label"),
            category=body.get("category"),
            created_by=body.get("created_by") or body.get("rater_id"),
            lat=body.get("lat"),
            lon=body.get("lon"),
            address=body.get("address"),
            ideal_minutes=body.get("ideal", 15),
            limit_minutes=body.get("limit", 30),
        )
        return jsonify(_anchor_json(anchor)), 201
    except (RatingValidationError, MapboxError) as exc:
        return jsonify(error=str(exc)), 400
    finally:
        session.close()


@api_bp.patch("/anchors/<int:anchor_id>")
def anchors_update(anchor_id):
    body = request.get_json(force=True, silent=True) or {}
    session = SessionLocal()
    try:
        anchor = update_anchor(
            session, anchor_id,
            ideal_minutes=body.get("ideal"), limit_minutes=body.get("limit"),
        )
        return jsonify(_anchor_json(anchor))
    except RatingValidationError as exc:
        return jsonify(error=str(exc)), 404
    finally:
        session.close()


@api_bp.delete("/anchors/<int:anchor_id>")
def anchors_delete(anchor_id):
    session = SessionLocal()
    try:
        delete_anchor(session, anchor_id)
        return "", 204
    except RatingValidationError as exc:
        return jsonify(error=str(exc)), 404
    finally:
        session.close()
