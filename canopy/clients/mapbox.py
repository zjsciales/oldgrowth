"""Mapbox Static Images API client -- current satellite imagery for the
Stage 5 vision sanity-check (chosen over the county's own aerial layer,
which is from 2016 and too stale to catch recent clear-cutting).

Zoom is set wide enough to show neighboring parcels, not just the subject
lot -- a first live test showed the sub-agent couldn't confirm water/park
adjacency from a tightly-cropped image, since those features often sit
just outside the parcel boundary."""

import requests

from canopy.config import MAPBOX_API_KEY

STATIC_IMAGE_URL = "https://api.mapbox.com/styles/v1/mapbox/satellite-v9/static/{lon},{lat},{zoom}/{width}x{height}"
GEOCODING_URL = "https://api.mapbox.com/search/geocode/v6/forward"

DEFAULT_ZOOM = 16
DEFAULT_SIZE = (800, 600)


class MapboxError(RuntimeError):
    pass


def fetch_satellite_image(latitude: float, longitude: float, zoom: int = DEFAULT_ZOOM) -> bytes:
    if not MAPBOX_API_KEY:
        raise MapboxError("MAPBOX_API_KEY is not set")

    width, height = DEFAULT_SIZE
    url = STATIC_IMAGE_URL.format(lon=longitude, lat=latitude, zoom=zoom, width=width, height=height)
    resp = requests.get(url, params={"access_token": MAPBOX_API_KEY}, timeout=30)
    if resp.status_code != 200:
        raise MapboxError(f"Mapbox static image request failed ({resp.status_code}): {resp.text[:300]}")
    return resp.content


def geocode_address(query: str) -> tuple[float, float] | None:
    """Forward-geocodes a free-text place/address via Mapbox's Geocoding
    v6 API (confirmed live). Returns (latitude, longitude), or None if
    nothing matched -- callers decide how to surface that (canopy/rating.py
    treats it as a validation error on anchor creation)."""
    if not MAPBOX_API_KEY:
        raise MapboxError("MAPBOX_API_KEY is not set")

    resp = requests.get(
        GEOCODING_URL, params={"q": query, "access_token": MAPBOX_API_KEY, "limit": 1}, timeout=15
    )
    if resp.status_code != 200:
        raise MapboxError(f"Mapbox geocoding request failed ({resp.status_code}): {resp.text[:300]}")

    features = resp.json().get("features", [])
    if not features:
        return None
    lon, lat = features[0]["geometry"]["coordinates"]
    return lat, lon
