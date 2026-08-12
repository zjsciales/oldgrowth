"""New Hanover County ArcGIS REST client.

Public, free, no API key. Layer paths below were confirmed by introspecting
https://gis.nhcgov.com/server/rest/services (via `?f=json` on each
MapServer/FeatureServer) during Stage 2 development -- not guessed. Native
spatial reference is NC State Plane (wkid 103122), units in US feet, which
is why buffer distances below are in feet.

Layers used (all verified live during development):
  Layers/Parcels/FeatureServer/0        - parcel polygon + PID + ACRES
  Layers/FloodHazards_2025/FeatureServer/16 - FEMA flood zones (FLOODZONE, SFHA_TF)
  Layers/wetlands_fwsnwi_2025/FeatureServer/0 - USFWS National Wetlands Inventory
  Layers/NHC_Parks_poly/MapServer/0     - county/city park polygons
  Layers/Easements/FeatureServer/0      - recorded easements (conservation + utility;
                                           ETYPE values not enumerated by the service,
                                           so this flag is broad, not conservation-only)
  Thematic/NHC_PropertiesAndBuildings/MapServer/2 - "NHC Properties" (county-owned parcels)

Layers/TidalCreeks was tried for open-water adjacency and dropped: despite
the name, its polygons are tidal-creek *watersheds* (drainage basins up to
~4,300 acres each, verified via a live query against a downtown/inland
address), not water bodies -- using it flagged nearly every parcel in the
county as "adjacent water". Open water is instead derived from the
wetlands layer's own WETLAND_TYPE, which includes real water-body classes
(see OPEN_WATER_TYPES below) alongside vegetated wetland classes.

No general canopy/tree-cover layer was found in this service catalog --
Stage 3 falls back to NLCD for that. No year-built field exists on any
layer checked (Parcels, Thematic/NHC_PropertiesAndBuildings's
Parcel_Polygon, PropertyOwners, IASTAX) -- the rating pivot's
median_year_built_buffer feature is computed from our own already-ingested
Listing.year_built rows instead (see canopy/features.py), not from GIS.

Layers/BuildingFootprints (real per-building polygons, joined to a parcel
via its own `Parcel_ID` field, confirmed to match Parcels.PID format) and
Layers/Roads (polyline, has an RDCLASS field for a possible future non-OSM
road-class source) were found during the rating-pivot feature work and are
used below for boundary/perimeter classification.
"""

import json
import time

import requests
from shapely.geometry import MultiLineString, Polygon, mapping
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

BASE_URL = "https://gis.nhcgov.com/server/rest/services"
NATIVE_SR = 103122  # NC State Plane, US feet
WGS84_SR = 4326

PARCELS_LAYER = "Layers/Parcels/FeatureServer/0"
FLOOD_LAYER = "Layers/FloodHazards_2025/FeatureServer/16"
WETLANDS_LAYER = "Layers/wetlands_fwsnwi_2025/FeatureServer/0"
PARKS_LAYER = "Layers/NHC_Parks_poly/MapServer/0"
EASEMENTS_LAYER = "Layers/Easements/FeatureServer/0"
COUNTY_PROPERTIES_LAYER = "Thematic/NHC_PropertiesAndBuildings/MapServer/2"
ROADS_LAYER = "Layers/Roads/FeatureServer/0"
BUILDING_FOOTPRINTS_LAYER = "Layers/BuildingFootprints/FeatureServer/0"

# Tolerance for treating a nearby feature as "touching" the parcel boundary.
# Small on purpose -- this is a digitizing-gap allowance (county polygons
# don't always share exact vertices with their neighbors), not a real
# adjacency distance like ADJACENCY_BUFFER_FT below.
BOUNDARY_TOUCH_FT = 5

# Search radius for the nearest neighboring building footprint.
FOOTPRINT_SEARCH_FT = 200

# wetlands_fwsnwi_2025.WETLAND_TYPE values that represent actual open water
# (river/lake/pond/estuary), as opposed to vegetated marsh/swamp classes
# ("Freshwater Emergent Wetland", "Freshwater Forested/Shrub Wetland",
# "Estuarine and Marine Wetland") which count toward wetland_overlay but
# not adjacent_water. Enumerated from a live query of the layer's distinct
# WETLAND_TYPE values during development.
OPEN_WATER_TYPES = {"Estuarine and Marine Deepwater", "Lake", "Riverine", "Freshwater Pond"}

ADJACENCY_BUFFER_FT = 50

MAX_RETRIES = 6
RETRY_BACKOFF_SECONDS = 3


class NHCGisError(RuntimeError):
    pass


def _query(layer_path: str, params: dict, method: str = "get") -> dict:
    request_fn = requests.post if method == "post" else requests.get
    kwarg = "data" if method == "post" else "params"

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = request_fn(
                f"{BASE_URL}/{layer_path}/query",
                timeout=30,
                **{kwarg: {**params, "f": "json"}},
            )
            if resp.status_code != 200:
                raise NHCGisError(f"GIS query failed ({resp.status_code}) for {layer_path}: {resp.text}")
            data = resp.json()
            if "error" in data:
                raise NHCGisError(f"GIS query error for {layer_path}: {data['error']}")
            return data
        except (NHCGisError, requests.RequestException) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))

    raise NHCGisError(f"GIS query failed after {MAX_RETRIES} attempts for {layer_path}: {last_error}")


def _esri_rings_to_polygon(geometry: dict) -> Polygon:
    """Assumes the first ring is exterior and any others are holes -- true
    for the vast majority of New Hanover parcels, which are single-part.

    Some source parcels are self-intersecting (bad digitizing on the
    county's end -- confirmed live on a condo unit parcel that produced a
    negative-area invalid polygon and, once buffered, a 400 from the GIS
    server). `buffer(0)` is the standard shapely repair idiom; if that
    still yields a MultiPolygon, keep the largest part."""
    rings = geometry["rings"]
    polygon = Polygon(rings[0], holes=rings[1:] if len(rings) > 1 else None)
    if not polygon.is_valid:
        repaired = polygon.buffer(0)
        if repaired.geom_type == "MultiPolygon":
            repaired = max(repaired.geoms, key=lambda g: g.area)
        polygon = repaired
    return polygon


def _polygon_to_esri_geometry(polygon: BaseGeometry, sr: int = NATIVE_SR) -> dict:
    coords = mapping(polygon)
    return {"rings": coords["coordinates"], "spatialReference": {"wkid": sr}}


def find_parcel_for_point(latitude: float, longitude: float) -> dict | None:
    """Point-in-polygon lookup against the county parcel layer. Returns the
    parcel's attributes + native-SR (feet) geometry, or None if not found."""
    data = _query(
        PARCELS_LAYER,
        {
            "geometry": f'{{"x":{longitude},"y":{latitude}}}',
            "geometryType": "esriGeometryPoint",
            "inSR": WGS84_SR,
            "outSR": NATIVE_SR,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*",
            "returnGeometry": "true",
        },
    )
    features = data.get("features", [])
    if not features:
        return None
    return features[0]


def _intersects_buffer(layer_path: str, buffer_geometry_esri: dict) -> list[dict]:
    data = _query(
        layer_path,
        {
            "geometry": json.dumps(buffer_geometry_esri),
            "geometryType": "esriGeometryPolygon",
            "inSR": NATIVE_SR,
            "spatialRel": "esriSpatialRelIntersects",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "false",
        },
        method="post",
    )
    return data.get("features", [])


def _intersects_buffer_with_geometry(layer_path: str, buffer_geometry_esri: dict) -> list[dict]:
    """Same as `_intersects_buffer`, but also returns each hit's geometry
    (native SR) -- needed for perimeter/area math, not just existence."""
    data = _query(
        layer_path,
        {
            "geometry": json.dumps(buffer_geometry_esri),
            "geometryType": "esriGeometryPolygon",
            "inSR": NATIVE_SR,
            "outSR": NATIVE_SR,
            "spatialRel": "esriSpatialRelIntersects",
            "where": "1=1",
            "outFields": "*",
            "returnGeometry": "true",
        },
        method="post",
    )
    return data.get("features", [])


def _esri_geometry_to_shape(geometry: dict) -> BaseGeometry:
    if "rings" in geometry:
        return _esri_rings_to_polygon(geometry)
    if "paths" in geometry:
        return MultiLineString(geometry["paths"])
    raise NHCGisError(f"unrecognized esri geometry shape: {list(geometry.keys())}")


def enrich_parcel(latitude: float, longitude: float) -> dict:
    """Full Stage 2 enrichment for one listing's coordinates. Deterministic,
    no AI involved: point-in-polygon + a fixed-distance buffer intersect
    against each thematic layer."""
    parcel = find_parcel_for_point(latitude, longitude)
    if parcel is None:
        return {
            "parcel_id": None,
            "geometry_geojson": None,
            "adjacent_water": False,
            "adjacent_park_or_conservation": False,
            "adjacent_county_or_city_owned": False,
            "flood_zone": None,
            "wetland_overlay": False,
            "raw_gis": {"parcel": None},
        }

    attrs = parcel["attributes"]
    parcel_polygon = _esri_rings_to_polygon(parcel["geometry"])
    buffered = parcel_polygon.buffer(ADJACENCY_BUFFER_FT)
    buffer_esri = _polygon_to_esri_geometry(buffered)

    park_hits = _intersects_buffer(PARKS_LAYER, buffer_esri)
    easement_hits = _intersects_buffer(EASEMENTS_LAYER, buffer_esri)
    county_hits = _intersects_buffer(COUNTY_PROPERTIES_LAYER, buffer_esri)
    wetland_hits_buffered = _intersects_buffer(WETLANDS_LAYER, buffer_esri)

    parcel_esri = _polygon_to_esri_geometry(parcel_polygon)
    flood_hits = _intersects_buffer(FLOOD_LAYER, parcel_esri)
    wetland_hits_on_parcel = _intersects_buffer(WETLANDS_LAYER, parcel_esri)

    flood_zone = None
    if flood_hits:
        flood_zone = flood_hits[0]["attributes"].get("FLOODZONE")

    adjacent_water = any(
        hit["attributes"].get("WETLAND_TYPE") in OPEN_WATER_TYPES for hit in wetland_hits_buffered
    )

    return {
        "parcel_id": attrs.get("PID"),
        "geometry_geojson": mapping(parcel_polygon),
        "adjacent_water": adjacent_water,
        "adjacent_park_or_conservation": bool(park_hits) or bool(easement_hits),
        "adjacent_county_or_city_owned": bool(county_hits),
        "flood_zone": flood_zone,
        "wetland_overlay": bool(wetland_hits_on_parcel),
        "raw_gis": {
            "parcel_attributes": attrs,
            "park_hits": len(park_hits),
            "easement_hits": len(easement_hits),
            "county_hits": len(county_hits),
            "flood_hits": [f["attributes"] for f in flood_hits],
            "wetland_hits_on_parcel": [f["attributes"] for f in wetland_hits_on_parcel],
            "wetland_hits_buffered": [f["attributes"] for f in wetland_hits_buffered],
        },
    }


def _side_of_point(x: float, y: float, minx: float, miny: float, maxx: float, maxy: float) -> str:
    """Nearest of the parcel's 4 bounding-box edges -- a coarse compass
    simplification (n/e/s/w) for the rating UI's stylized ParcelPlate,
    not a precise per-vertex classification."""
    distances = {"n": maxy - y, "s": y - miny, "e": maxx - x, "w": x - minx}
    return min(distances, key=distances.get)


def compute_boundary_features(parcel_polygon: Polygon) -> dict:
    """Classify the parcel's OWN perimeter by what actually touches it,
    rather than enrich_parcel()'s coarser "any hit within 50ft" adjacency
    test. Powers ListingFeatures.protected_perimeter_ratio/abuts_*, and
    `edges` resolves a dominant touching type per compass side (n/e/s/w)
    so the rating UI can render its ParcelPlate from a cached value
    instead of a live GIS query per view (raw geometry never goes to the
    client -- UI_SPEC.md §5).

    `abuts_buildable_private` covers whatever's left of the perimeter once
    protected land and roads are subtracted -- it's the "someone can build
    behind it" risk case. `edges` categories match the UI's EDGE_META
    exactly: water / marsh / park / conservation / road / buildable."""
    boundary = parcel_polygon.exterior
    total_perimeter = boundary.length
    if total_perimeter == 0:
        return {
            "protected_perimeter_ratio": None,
            "abuts_water": False,
            "abuts_marsh_wetland": False,
            "abuts_park_public": False,
            "abuts_conservation_easement": False,
            "abuts_buildable_private": False,
            "edges": {"n": "buildable", "e": "buildable", "s": "buildable", "w": "buildable"},
            "raw_boundary": {},
        }

    minx, miny, maxx, maxy = parcel_polygon.bounds
    touch_esri = _polygon_to_esri_geometry(parcel_polygon.buffer(BOUNDARY_TOUCH_FT))
    park_hits = _intersects_buffer_with_geometry(PARKS_LAYER, touch_esri)
    easement_hits = _intersects_buffer_with_geometry(EASEMENTS_LAYER, touch_esri)
    county_hits = _intersects_buffer_with_geometry(COUNTY_PROPERTIES_LAYER, touch_esri)
    wetland_hits = _intersects_buffer_with_geometry(WETLANDS_LAYER, touch_esri)
    road_hits = _intersects_buffer_with_geometry(ROADS_LAYER, touch_esri)

    side_lengths: dict[str, dict[str, float]] = {}

    def touching_length(hits: list[dict], category: str) -> float:
        total = 0.0
        for hit in hits:
            shape = _esri_geometry_to_shape(hit["geometry"])
            touched = boundary.intersection(shape.buffer(BOUNDARY_TOUCH_FT))
            length = touched.length
            total += length
            if length == 0:
                continue
            centroid = touched.centroid
            side = _side_of_point(centroid.x, centroid.y, minx, miny, maxx, maxy)
            side_lengths.setdefault(side, {})
            side_lengths[side][category] = side_lengths[side].get(category, 0.0) + length
        return total

    water_hits = [h for h in wetland_hits if h["attributes"].get("WETLAND_TYPE") in OPEN_WATER_TYPES]
    marsh_hits = [h for h in wetland_hits if h["attributes"].get("WETLAND_TYPE") not in OPEN_WATER_TYPES]

    park_len = touching_length(park_hits + county_hits, "park")
    conservation_len = touching_length(easement_hits, "conservation")
    water_len = touching_length(water_hits, "water")
    marsh_len = touching_length(marsh_hits, "marsh")
    road_len = touching_length(road_hits, "road")

    protected_len = min(total_perimeter, park_len + conservation_len + water_len + marsh_len)
    buildable_len = max(0.0, total_perimeter - protected_len - road_len)

    edges = {}
    for side in ("n", "e", "s", "w"):
        categories = side_lengths.get(side)
        edges[side] = max(categories, key=categories.get) if categories else "buildable"

    return {
        "protected_perimeter_ratio": protected_len / total_perimeter,
        "abuts_water": water_len > 0,
        "abuts_marsh_wetland": marsh_len > 0,
        "abuts_park_public": bool(park_hits),
        "abuts_conservation_easement": bool(easement_hits),
        "abuts_buildable_private": buildable_len > 0,
        "edges": edges,
        "raw_boundary": {
            "total_perimeter_ft": total_perimeter,
            "park_touch_ft": park_len,
            "conservation_touch_ft": conservation_len,
            "water_touch_ft": water_len,
            "marsh_touch_ft": marsh_len,
            "road_touch_ft": road_len,
            "buildable_touch_ft": buildable_len,
        },
    }


def wetland_pct_of_parcel(parcel_polygon: Polygon) -> float | None:
    """Own-parcel wetland coverage -- cuts both ways (adds privacy, costs
    usable yard), separate from the boundary-touching wetland/marsh
    adjacency in compute_boundary_features()."""
    if parcel_polygon.area == 0:
        return None
    parcel_esri = _polygon_to_esri_geometry(parcel_polygon)
    hits = _intersects_buffer_with_geometry(WETLANDS_LAYER, parcel_esri)
    if not hits:
        return 0.0
    total_area = 0.0
    for hit in hits:
        shape = _esri_geometry_to_shape(hit["geometry"])
        total_area += parcel_polygon.intersection(shape).area
    return min(1.0, total_area / parcel_polygon.area)


def rear_open_distance_ft(parcel_polygon: Polygon, parcel_id: str) -> float | None:
    """Distance from the subject's own building footprint to the nearest
    neighboring footprint, via Layers/BuildingFootprints (real per-building
    polygons, joined on Parcel_ID -- confirmed live to match Parcels.PID
    format). Returns None if the subject parcel has no footprint (vacant
    lot) or no neighboring footprint is within FOOTPRINT_SEARCH_FT --
    callers should treat None as imputed, not zero."""
    search_esri = _polygon_to_esri_geometry(parcel_polygon.buffer(FOOTPRINT_SEARCH_FT))
    hits = _intersects_buffer_with_geometry(BUILDING_FOOTPRINTS_LAYER, search_esri)
    own = [h for h in hits if h["attributes"].get("Parcel_ID") == parcel_id]
    others = [h for h in hits if h["attributes"].get("Parcel_ID") != parcel_id]
    if not own or not others:
        return None

    own_shape = unary_union([_esri_geometry_to_shape(h["geometry"]) for h in own])
    return min(own_shape.distance(_esri_geometry_to_shape(h["geometry"])) for h in others)
