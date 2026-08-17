"""Stage 2 (features): the full feature vector per docs/FEATURE_SCHEMA.md.
Every listing gets a row here -- missing values are imputed as None and
flagged in `imputed_fields`, never used to eliminate a listing. Structure/
architecture fields (arch_style etc.) are NOT computed here -- they're
populated lazily on first view by canopy/vision.py, to avoid running
Claude vision on the full weekly listing volume."""

import datetime as dt
import logging
import math

from shapely.geometry import mapping, shape
from sqlalchemy.orm import Session

from canopy.clients import canopy_raster, nhc_gis
from canopy.db.models import Anchor, Listing, ListingAnchorTime, ListingFeatures, Parcel, Score

logger = logging.getLogger(__name__)

FEATURE_SET_VERSION = "v1"

# Rollup categories match Anchor.category values (UI_SPEC.md's Places tab:
# beach / grocery / social / work / school). MIN for "closest one is what
# matters" categories, MEAN for social -- proximity to a whole network of
# people, not just the nearest one.
ANCHOR_ROLLUP_SPECS = [
    ("min_drive_beach", "beach", "min"),
    ("min_drive_grocery", "grocery", "min"),
    ("min_drive_work", "work", "min"),
    ("min_drive_school", "school", "min"),
    ("mean_drive_social", "social", "mean"),
]

# Matches scoring.py's existing constant -- Parcel.geometry_geojson is
# stored in this CRS (NC State Plane, US feet).
PARCEL_GEOMETRY_CRS = "ESRI:103122"

NEIGHBORHOOD_CANOPY_BUFFER_M = 150
YEAR_BUILT_BUFFER_FT = 500

# is_tract_new_build: a lone custom-built infill and a mass-built tract
# subdivision both have a recent year_built, but only the tract case has
# many nearby listings sharing that same recent year (median_year_built_buffer
# clustered tightly around it). First-pass constants, not yet spot-checked
# against real known-tract vs. known-custom-infill addresses -- see
# docs/CLAUDE.md's exclusion-exception note: this backs a soft veto
# (canopy/model.py's detect_vetoes), never a hard filter.
NEW_BUILD_RECENT_YEARS = 5
NEW_BUILD_CLUSTER_TOLERANCE_YEARS = 3

EARTH_RADIUS_FT = 20925646.325


def _haversine_ft(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_FT * math.asin(math.sqrt(a))


def _lot_dimensions(parcel_polygon, fallback_sqft: float | None) -> tuple[float | None, float | None, float | None]:
    """acreage, depth (long side), width (short side) of the parcel's
    minimum rotated bounding rectangle -- depth > width is a heuristic,
    not guaranteed for irregular lots. Falls back to the listing's
    RentCast-reported lot size for acreage (real data, just less precise)
    when parcel geometry isn't available; depth/width need geometry."""
    if parcel_polygon is None or parcel_polygon.area == 0:
        acreage = fallback_sqft / 43560 if fallback_sqft else None
        return acreage, None, None

    acreage = parcel_polygon.area / 43560
    rect = parcel_polygon.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)
    side_lengths = [
        ((coords[i][0] - coords[i + 1][0]) ** 2 + (coords[i][1] - coords[i + 1][1]) ** 2) ** 0.5
        for i in range(len(coords) - 1)
    ]
    unique_sides = sorted(set(round(s, 2) for s in side_lengths))
    width, depth = (unique_sides[0], unique_sides[0]) if len(unique_sides) == 1 else (unique_sides[0], unique_sides[-1])
    return acreage, depth, width


def _median_year_built_buffer(session: Session, listing: Listing, radius_ft: float = YEAR_BUILT_BUFFER_FT) -> int | None:
    """Median year_built among OTHER already-ingested listings within
    radius_ft. No NHC GIS layer exposes year-built (checked Parcels,
    Parcel_Polygon, PropertyOwners, IASTAX -- confirmed live, none have
    it), so this uses our own already-ingested Listing rows instead of a
    GIS call. Coverage is necessarily partial (only areas we've ingested
    listings in) -- that's fine, it's imputed+flagged like anything else
    missing, never used to eliminate a listing."""
    if listing.latitude is None or listing.longitude is None:
        return None
    deg_pad = (radius_ft / 364000) * 1.5  # rough bounding-box prefilter before the precise haversine trim
    candidates = (
        session.query(Listing)
        .filter(Listing.id != listing.id)
        .filter(Listing.year_built.isnot(None))
        .filter(Listing.latitude.isnot(None))
        .filter(Listing.longitude.isnot(None))
        .filter(Listing.latitude.between(listing.latitude - deg_pad, listing.latitude + deg_pad))
        .filter(Listing.longitude.between(listing.longitude - deg_pad, listing.longitude + deg_pad))
        .all()
    )
    nearby_years = sorted(
        c.year_built for c in candidates
        if _haversine_ft(listing.latitude, listing.longitude, c.latitude, c.longitude) <= radius_ft
    )
    if not nearby_years:
        return None
    n = len(nearby_years)
    mid = n // 2
    return nearby_years[mid] if n % 2 else round((nearby_years[mid - 1] + nearby_years[mid]) / 2)


def _market_fields(listing: Listing) -> dict:
    """days_on_market / hoa_fee_monthly / price_cut_count, all derived from
    the already-stored RentCast raw payload -- no new API calls. Field
    names verified against real payloads, not guessed."""
    raw = listing.raw or {}

    days_on_market = raw.get("daysOnMarket")
    if days_on_market is None and listing.listed_date:
        days_on_market = (dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - listing.listed_date).days

    hoa = raw.get("hoa")
    hoa_fee_monthly = hoa.get("fee") if isinstance(hoa, dict) else None

    history = raw.get("history") or {}
    prices = [entry.get("price") for _, entry in sorted(history.items()) if entry.get("price") is not None]
    price_cut_count = sum(1 for prev, cur in zip(prices, prices[1:]) if cur < prev)

    return {
        "days_on_market": days_on_market,
        "hoa_fee_monthly": hoa_fee_monthly,
        "price_cut_count": price_cut_count,
    }


def _dominant_road_class(edges: dict | None, road_edges: dict | None) -> str | None:
    """Among the sides whose dominant touching category is actually
    "road" (per compute_boundary_features' `edges`), pick the
    classification of whichever has the longest real road touch --
    matters for corner lots where two sides can both be roads."""
    road_sides = [side for side, kind in (edges or {}).items() if kind == "road"]
    candidates = [road_edges[side] for side in road_sides if road_edges and side in road_edges]
    if not candidates:
        return None
    best = max(candidates, key=lambda info: info.get("touch_len_ft", 0))
    return best.get("road_class")


def compute_feature_vector(session: Session, listing: Listing, parcel: Parcel | None, score: Score | None) -> dict:
    imputed: list[str] = []

    parcel_polygon = None
    if parcel and parcel.geometry_geojson:
        parcel_polygon = shape(parcel.geometry_geojson)

    parcel_outline = nhc_gis.simplify_parcel_outline_ft(parcel_polygon) if parcel_polygon is not None else None

    acreage, depth, width = _lot_dimensions(parcel_polygon, listing.lot_size_sqft)
    if acreage is None:
        imputed.append("lot_acreage")
    if depth is None:
        imputed += ["lot_depth_ft", "lot_width_ft"]

    boundary: dict = {}
    if parcel_polygon is not None:
        boundary = nhc_gis.compute_boundary_features(parcel_polygon)
    else:
        imputed += [
            "protected_perimeter_ratio", "abuts_water", "abuts_marsh_wetland",
            "abuts_park_public", "abuts_conservation_easement", "abuts_buildable_private",
        ]

    # Real classification from the county's own Roads layer (RDCLASS),
    # not OSM -- see nhc_gis.RDCLASS_TO_ROAD_CLASS. dist_to_arterial_m/
    # is_cul_de_sac/is_dead_end/through_traffic_proxy/front_setback_ft
    # remain reserved/unpopulated pending real OSM integration
    # (docs/FEATURE_SCHEMA.md §2.3) -- this is the one road & position
    # field the county's data can answer on its own.
    fronting_road_class = _dominant_road_class(boundary.get("edges"), boundary.get("road_edges"))
    if fronting_road_class is None:
        imputed.append("fronting_road_class")

    wetland_pct = nhc_gis.wetland_pct_of_parcel(parcel_polygon) if parcel_polygon is not None else None
    if wetland_pct is None:
        imputed.append("wetland_pct_of_parcel")

    rear_open = None
    if parcel_polygon is not None and parcel and parcel.parcel_id:
        rear_open = nhc_gis.rear_open_distance_ft(parcel_polygon, parcel.parcel_id)
    if rear_open is None:
        imputed.append("rear_open_distance_ft")

    parcel_canopy = score.canopy_pct if score else None
    if parcel_canopy is None:
        imputed.append("parcel_canopy_pct")

    neighborhood_canopy = None
    if parcel_polygon is not None:
        neighborhood_canopy = canopy_raster.neighborhood_canopy_buffer_pct(
            mapping(parcel_polygon), PARCEL_GEOMETRY_CRS, buffer_m=NEIGHBORHOOD_CANOPY_BUFFER_M
        )
    if neighborhood_canopy is None:
        imputed.append("neighborhood_canopy_pct")

    canopy_delta = None
    if neighborhood_canopy is not None and parcel_canopy is not None:
        canopy_delta = neighborhood_canopy - parcel_canopy
    else:
        imputed.append("canopy_delta")

    median_year = _median_year_built_buffer(session, listing)
    if median_year is None:
        imputed.append("median_year_built_buffer")

    is_tract_new_build = None
    if listing.year_built is not None and median_year is not None:
        current_year = dt.date.today().year
        is_tract_new_build = (
            (current_year - listing.year_built) <= NEW_BUILD_RECENT_YEARS
            and abs(median_year - listing.year_built) <= NEW_BUILD_CLUSTER_TOLERANCE_YEARS
        )
    else:
        imputed.append("is_tract_new_build")

    canopy_age_proxy = None
    if neighborhood_canopy is not None and median_year is not None:
        # composite heuristic, explicitly not ground-truth -- validate
        # against ratings before trusting, per FEATURE_SCHEMA.md §2.2
        age_component = min(max(dt.date.today().year - median_year, 0) / 100, 1.0)
        canopy_age_proxy = 0.5 * (neighborhood_canopy / 100) + 0.5 * age_component
    else:
        imputed.append("canopy_age_proxy")

    market = _market_fields(listing)
    for key in ("days_on_market", "hoa_fee_monthly"):
        if market[key] is None:
            imputed.append(key)

    price_per_sqft = None
    if listing.price and listing.square_footage:
        price_per_sqft = listing.price / listing.square_footage
    else:
        imputed.append("price_per_sqft")

    raw = listing.raw or {}
    beds = raw.get("bedrooms")
    baths = raw.get("bathrooms")
    if beds is None:
        imputed.append("beds")
    if baths is None:
        imputed.append("baths")
    imputed.append("stories")  # RentCast never returns this field (verified)

    avg_room_sqft = None
    if listing.square_footage and beds:
        avg_room_sqft = listing.square_footage / beds
    else:
        imputed.append("avg_room_sqft")

    return {
        "listing_id": listing.id,
        "feature_set_version": FEATURE_SET_VERSION,
        "lot_acreage": acreage,
        "lot_depth_ft": depth,
        "lot_width_ft": width,
        "protected_perimeter_ratio": boundary.get("protected_perimeter_ratio"),
        "abuts_water": boundary.get("abuts_water"),
        "abuts_marsh_wetland": boundary.get("abuts_marsh_wetland"),
        "abuts_park_public": boundary.get("abuts_park_public"),
        "abuts_conservation_easement": boundary.get("abuts_conservation_easement"),
        "abuts_buildable_private": boundary.get("abuts_buildable_private"),
        "fronting_road_class": fronting_road_class,
        "rear_open_distance_ft": rear_open,
        "wetland_pct_of_parcel": wetland_pct,
        "flood_zone": parcel.flood_zone if parcel else None,
        "parcel_canopy_pct": parcel_canopy,
        "neighborhood_canopy_pct": neighborhood_canopy,
        "canopy_delta": canopy_delta,
        "median_year_built_buffer": median_year,
        "canopy_age_proxy": canopy_age_proxy,
        "is_tract_new_build": is_tract_new_build,
        "year_built": listing.year_built,
        "sqft": listing.square_footage,
        "beds": beds,
        "baths": baths,
        "stories": None,
        "avg_room_sqft": avg_room_sqft,
        "list_price": listing.price,
        "price_per_sqft": price_per_sqft,
        "days_on_market": market["days_on_market"],
        "price_cut_count": market["price_cut_count"],
        "hoa_fee_monthly": market["hoa_fee_monthly"],
        "imputed_fields": imputed,
        "extra": {
            # dominant abutting type per compass side (n/e/s/w), cached here
            # so the rating API can serve ListingCard.edges without a live
            # GIS query (UI_SPEC.md §5)
            **({"edges": boundary.get("edges")} if boundary.get("edges") else {}),
            # simplified real parcel outline, centroid-relative feet --
            # ParcelPlate draws this instead of a placeholder rectangle
            **({"parcel_outline": parcel_outline} if parcel_outline else {}),
            # real road centerline geometry + name/classification per
            # touching side (nhc_gis.compute_boundary_features) --
            # ParcelPlate draws the actual fronting street shape instead
            # of a flat compass band
            **({"road_edges": boundary.get("road_edges")} if boundary.get("road_edges") else {}),
        },
    }


def compute_features_for_listings(session: Session, listings: list[Listing]) -> list[ListingFeatures]:
    results: list[ListingFeatures] = []

    for listing in listings:
        parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
        score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()
        vector = compute_feature_vector(session, listing, parcel, score)

        row = (
            session.query(ListingFeatures)
            .filter_by(listing_id=listing.id, feature_set_version=FEATURE_SET_VERSION)
            .one_or_none()
        )
        if row is None:
            row = ListingFeatures(listing_id=listing.id, feature_set_version=FEATURE_SET_VERSION)
            session.add(row)

        for key, value in vector.items():
            if key in ("listing_id", "feature_set_version"):
                continue
            setattr(row, key, value)
        row.computed_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

        session.commit()  # per-listing, so a mid-run failure doesn't lose progress
        results.append(row)
        logger.info(
            "features %s: canopy=%s neighborhood_canopy=%s protected_perimeter=%s imputed=%d",
            listing.id, row.parcel_canopy_pct, row.neighborhood_canopy_pct,
            row.protected_perimeter_ratio, len(row.imputed_fields or []),
        )

    return results


def anchor_rollups(session: Session, listing_id: str) -> dict:
    """min/mean drive time per anchor category, computed on the fly at
    model-input-assembly time (canopy/model.py) -- not persisted as
    ListingFeatures columns, per FEATURE_SCHEMA.md §2.4. Reads whatever
    ListingAnchorTime rows already exist (populated lazily by
    canopy.rating.ensure_anchor_times); a category with no active anchors
    yet, or no computed times, comes back None -- imputed at model-fit
    time, same as everything else missing."""
    rows = (
        session.query(ListingAnchorTime, Anchor)
        .join(Anchor, Anchor.id == ListingAnchorTime.anchor_id)
        .filter(ListingAnchorTime.listing_id == listing_id)
        .filter(Anchor.active.is_(True))
        .filter(ListingAnchorTime.drive_minutes.isnot(None))
        .all()
    )
    minutes_by_category: dict[str, list[float]] = {}
    for lat_row, anchor in rows:
        minutes_by_category.setdefault(anchor.category, []).append(lat_row.drive_minutes)

    rollups: dict[str, float | None] = {}
    for feature_name, category, agg in ANCHOR_ROLLUP_SPECS:
        minutes = minutes_by_category.get(category)
        if not minutes:
            rollups[feature_name] = None
        elif agg == "min":
            rollups[feature_name] = min(minutes)
        else:
            rollups[feature_name] = sum(minutes) / len(minutes)
    return rollups
