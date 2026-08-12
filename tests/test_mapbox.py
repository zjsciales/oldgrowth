import responses

from canopy.clients.mapbox import GEOCODING_URL, WILMINGTON_METRO_BBOX, geocode_address


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
