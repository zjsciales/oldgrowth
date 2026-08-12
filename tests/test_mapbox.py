import responses

from canopy.clients.mapbox import GEOCODING_URL, geocode_address


@responses.activate
def test_geocode_address_returns_lat_lon():
    responses.add(
        responses.GET, GEOCODING_URL,
        json={"features": [{"geometry": {"type": "Point", "coordinates": [-77.8195, 34.2219]}}]},
        status=200,
    )

    result = geocode_address("Wrightsville Beach public access")

    assert result == (34.2219, -77.8195)


@responses.activate
def test_geocode_address_returns_none_when_no_match():
    responses.add(responses.GET, GEOCODING_URL, json={"features": []}, status=200)

    assert geocode_address("asdkjhaslkdjhas nonsense") is None
