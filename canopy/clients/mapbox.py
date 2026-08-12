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

# Anchors only ever make sense within the app's actual service area (same
# metro TARGET_ZIPS already scopes ingest to). Without this, Mapbox's
# forward geocoding is dangerously permissive for loose text: confirmed
# live that "asdkjaslkdjaslkdj nonsense query" and even "Wrightsville
# Beach public access" (a real local landmark, phrased loosely) both
# silently matched to unrelated streets on the other side of the country
# with no match_code/confidence signal to catch it -- country=US alone
# wasn't enough. Restricting to this bbox makes garbage queries correctly
# return no match, while real local landmark phrasing still resolves.
WILMINGTON_METRO_BBOX = "-78.15,33.95,-77.75,34.35"


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


def geocode_address(query: str) -> tuple[float, float, str] | None:
    """Forward-geocodes a free-text place/address via Mapbox's Geocoding
    v6 API, scoped to WILMINGTON_METRO_BBOX (confirmed live -- see that
    constant's comment for why the bbox restriction is load-bearing, not
    optional). Returns (latitude, longitude, full_address), or None if
    nothing matched -- callers decide how to surface that (canopy/rating.py
    treats it as a validation error on anchor creation). full_address is
    the Mapbox-resolved address, returned so the caller can show the user
    what actually got matched rather than trusting the input silently."""
    if not MAPBOX_API_KEY:
        raise MapboxError("MAPBOX_API_KEY is not set")

    resp = requests.get(
        GEOCODING_URL,
        params={
            "q": query, "access_token": MAPBOX_API_KEY, "limit": 1,
            "country": "US", "bbox": WILMINGTON_METRO_BBOX,
        },
        timeout=15,
    )
    if resp.status_code != 200:
        raise MapboxError(f"Mapbox geocoding request failed ({resp.status_code}): {resp.text[:300]}")

    features = resp.json().get("features", [])
    if not features:
        return None
    properties = features[0]["properties"]
    lon, lat = features[0]["geometry"]["coordinates"]
    full_address = properties.get("full_address") or properties.get("name") or query
    return lat, lon, full_address
