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
Stage 3 falls back to NLCD for that.
"""

import json
import time

import requests
from shapely.geometry import Polygon, mapping
from shapely.geometry.base import BaseGeometry

BASE_URL = "https://gis.nhcgov.com/server/rest/services"
NATIVE_SR = 103122  # NC State Plane, US feet
WGS84_SR = 4326

PARCELS_LAYER = "Layers/Parcels/FeatureServer/0"
FLOOD_LAYER = "Layers/FloodHazards_2025/FeatureServer/16"
WETLANDS_LAYER = "Layers/wetlands_fwsnwi_2025/FeatureServer/0"
PARKS_LAYER = "Layers/NHC_Parks_poly/MapServer/0"
EASEMENTS_LAYER = "Layers/Easements/FeatureServer/0"
COUNTY_PROPERTIES_LAYER = "Thematic/NHC_PropertiesAndBuildings/MapServer/2"

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
