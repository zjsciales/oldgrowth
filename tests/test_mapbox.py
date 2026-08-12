import re

import responses

from canopy.clients.mapbox import GEOCODING_URL, WILMINGTON_METRO_BBOX, fetch_location_map, geocode_address


@responses.activate
def test_fetch_location_map_returns_image_bytes():
    responses.add(responses.GET, re.compile(r".*"), body=b"fake-png-bytes", content_type="image/png")

    result = fetch_location_map(34.165672, -77.927776)

    assert result == b"fake-png-bytes"


@responses.activate
def test_fetch_location_map_centers_bbox_and_marker_on_the_listing():
    responses.add(responses.GET, re.compile(r".*"), body=b"fake-png-bytes", content_type="image/png")

    fetch_location_map(34.165672, -77.927776, radius_miles=1.0)

    request_url = responses.calls[0].request.url
    # marker pin sits at the listing's exact coordinates (verified live:
    # requests leaves the parens/comma in this path segment unencoded)
    assert "pin-s+3E6B45(-77.927776,34.165672)" in request_url
    # bbox brackets the listing symmetrically, roughly 1 mile in each
    # direction (verified live: requests percent-encodes the brackets)
    assert "%5B-77.945" in request_url  # west edge
    assert "34.151" in request_url  # south edge
    assert "-77.910" in request_url  # east edge
    assert "34.180" in request_url  # north edge


@responses.activate
def test_geocode_address_returns_lat_lon_and_resolved_address():
    responses.add(
        responses.GET, GEOCODING_URL,
        json={
            "features": [{
                "geometry": {"type": "Point", "coordinates": [-77.8195, 34.2219]},
                "properties": {"full_address": "Wrightsville Beach, North Carolina, United States"},
            }]
        },
        status=200,
    )

    result = geocode_address("Wrightsville Beach public access")

    assert result == (34.2219, -77.8195, "Wrightsville Beach, North Carolina, United States")


@responses.activate
def test_geocode_address_scopes_to_wilmington_metro_bbox():
    """Load-bearing, not incidental: unscoped forward geocoding silently
    matched nonsense/loose queries to unrelated streets across the
    country (confirmed live) -- the bbox restriction is what makes
    garbage queries correctly return no match."""
    responses.add(responses.GET, GEOCODING_URL, json={"features": []}, status=200)

    geocode_address("Wrightsville Beach public access")

    request_url = responses.calls[0].request.url
    assert f"bbox={WILMINGTON_METRO_BBOX.replace(',', '%2C')}" in request_url
    assert "country=US" in request_url


@responses.activate
def test_geocode_address_returns_none_when_no_match():
    responses.add(responses.GET, GEOCODING_URL, json={"features": []}, status=200)

    assert geocode_address("asdkjhaslkdjhas nonsense") is None
