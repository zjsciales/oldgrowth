import json
from pathlib import Path

import responses

from canopy.clients.nhc_gis import (
    BASE_URL,
    COUNTY_PROPERTIES_LAYER,
    EASEMENTS_LAYER,
    FLOOD_LAYER,
    PARCELS_LAYER,
    PARKS_LAYER,
    WETLANDS_LAYER,
    _esri_rings_to_polygon,
    enrich_parcel,
)

PARCEL_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "nhc_gis_parcel_query.json").read_text()
)


def _empty(url):
    responses.add(responses.POST, url, json={"features": []}, status=200)


@responses.activate
def test_enrich_parcel_no_hits():
    responses.add(
        responses.GET, f"{BASE_URL}/{PARCELS_LAYER}/query", json=PARCEL_FIXTURE, status=200
    )
    for layer in (PARKS_LAYER, EASEMENTS_LAYER, COUNTY_PROPERTIES_LAYER, FLOOD_LAYER):
        _empty(f"{BASE_URL}/{layer}/query")
    # queried twice per parcel: once buffered (adjacency), once on-parcel (overlay)
    _empty(f"{BASE_URL}/{WETLANDS_LAYER}/query")
    _empty(f"{BASE_URL}/{WETLANDS_LAYER}/query")

    result = enrich_parcel(34.2, -77.9)

    assert result["parcel_id"] == "R05511-999-001-000"
    assert result["adjacent_water"] is False
    assert result["adjacent_park_or_conservation"] is False
    assert result["adjacent_county_or_city_owned"] is False
    assert result["flood_zone"] is None
    assert result["wetland_overlay"] is False


@responses.activate
def test_enrich_parcel_with_hits():
    responses.add(
        responses.GET, f"{BASE_URL}/{PARCELS_LAYER}/query", json=PARCEL_FIXTURE, status=200
    )
    responses.add(
        responses.POST,
        f"{BASE_URL}/{PARKS_LAYER}/query",
        json={"features": [{"attributes": {"NAME": "Test Park"}}]},
        status=200,
    )
    responses.add(
        responses.POST,
        f"{BASE_URL}/{FLOOD_LAYER}/query",
        json={"features": [{"attributes": {"FLOODZONE": "AE"}}]},
        status=200,
    )
    # 1st WETLANDS_LAYER call is the buffered (adjacency) query -- an open-water hit
    responses.add(
        responses.POST,
        f"{BASE_URL}/{WETLANDS_LAYER}/query",
        json={"features": [{"attributes": {"WETLAND_TYPE": "Lake"}}]},
        status=200,
    )
    # 2nd WETLANDS_LAYER call is the on-parcel (overlay) query -- a vegetated wetland hit
    responses.add(
        responses.POST,
        f"{BASE_URL}/{WETLANDS_LAYER}/query",
        json={"features": [{"attributes": {"WETLAND_TYPE": "Freshwater Forested/Shrub Wetland"}}]},
        status=200,
    )
    for layer in (EASEMENTS_LAYER, COUNTY_PROPERTIES_LAYER):
        _empty(f"{BASE_URL}/{layer}/query")

    result = enrich_parcel(34.2, -77.9)

    assert result["adjacent_park_or_conservation"] is True
    assert result["flood_zone"] == "AE"
    assert result["adjacent_water"] is True
    assert result["wetland_overlay"] is True


@responses.activate
def test_enrich_parcel_wetland_type_distinguishes_water_from_marsh():
    """A vegetated marsh hit in the buffer should NOT set adjacent_water --
    only real open-water WETLAND_TYPE values should."""
    responses.add(
        responses.GET, f"{BASE_URL}/{PARCELS_LAYER}/query", json=PARCEL_FIXTURE, status=200
    )
    for layer in (PARKS_LAYER, EASEMENTS_LAYER, COUNTY_PROPERTIES_LAYER, FLOOD_LAYER):
        _empty(f"{BASE_URL}/{layer}/query")
    responses.add(
        responses.POST,
        f"{BASE_URL}/{WETLANDS_LAYER}/query",
        json={"features": [{"attributes": {"WETLAND_TYPE": "Freshwater Emergent Wetland"}}]},
        status=200,
    )
    _empty(f"{BASE_URL}/{WETLANDS_LAYER}/query")

    result = enrich_parcel(34.2, -77.9)

    assert result["adjacent_water"] is False


def test_esri_rings_to_polygon_repairs_self_intersecting_ring():
    # bowtie/figure-eight ring -- invalid, seen live on a real county condo
    # unit parcel. Must self-heal instead of producing a broken/garbage
    # geometry that the GIS server rejects with a 400 once buffered.
    bowtie_ring = [[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]

    polygon = _esri_rings_to_polygon({"rings": [bowtie_ring]})

    assert polygon.is_valid
    assert polygon.geom_type == "Polygon"


@responses.activate
def test_enrich_parcel_no_parcel_found():
    responses.add(
        responses.GET, f"{BASE_URL}/{PARCELS_LAYER}/query", json={"features": []}, status=200
    )

    result = enrich_parcel(0.0, 0.0)

    assert result["parcel_id"] is None
    assert result["adjacent_water"] is False
