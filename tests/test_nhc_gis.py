import json
from pathlib import Path

import pytest
import responses

from shapely.geometry import Polygon

from canopy.clients.nhc_gis import (
    BASE_URL,
    BUILDING_FOOTPRINTS_LAYER,
    COUNTY_PROPERTIES_LAYER,
    EASEMENTS_LAYER,
    FLOOD_LAYER,
    PARCELS_LAYER,
    PARKS_LAYER,
    ROADS_LAYER,
    WETLANDS_LAYER,
    _esri_rings_to_polygon,
    compute_boundary_features,
    enrich_parcel,
    rear_open_distance_ft,
    wetland_pct_of_parcel,
)

# 100x100 ft square at the origin -- perimeter 400ft, area 10000 sqft
SQUARE_PARCEL = Polygon([(0, 0), (0, 100), (100, 100), (100, 0), (0, 0)])


def _polygon_feature(attrs, rings):
    return {"attributes": attrs, "geometry": {"rings": rings}}

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


def _empty_geom(layer):
    responses.add(responses.POST, f"{BASE_URL}/{layer}/query", json={"features": []}, status=200)


@responses.activate
def test_compute_boundary_features_classifies_protected_and_buildable_edges():
    # park strip touching the north edge (y=100), water strip touching the
    # south edge (y=0) -- east/west edges touch nothing, so they should
    # read as buildable-private.
    responses.add(
        responses.POST, f"{BASE_URL}/{PARKS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"NAME": "Test Park"}, [[[0, 100], [0, 120], [100, 120], [100, 100], [0, 100]]]
        )]}, status=200,
    )
    responses.add(
        responses.POST, f"{BASE_URL}/{WETLANDS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"WETLAND_TYPE": "Lake"}, [[[0, -20], [0, 0], [100, 0], [100, -20], [0, -20]]]
        )]}, status=200,
    )
    for layer in (EASEMENTS_LAYER, COUNTY_PROPERTIES_LAYER, ROADS_LAYER):
        _empty_geom(layer)

    result = compute_boundary_features(SQUARE_PARCEL)

    assert result["abuts_park_public"] is True
    assert result["abuts_water"] is True
    assert result["abuts_marsh_wetland"] is False
    assert result["abuts_conservation_easement"] is False
    assert result["abuts_buildable_private"] is True
    # not exactly 0.5 -- the touch-tolerance buffer rounds corners, picking
    # up a sliver of the adjacent east/west edges near each corner
    assert result["protected_perimeter_ratio"] == pytest.approx(0.5, abs=0.1)


@responses.activate
def test_compute_boundary_features_resolves_dominant_type_per_compass_side():
    # park strip touching the north edge, water strip touching the south
    # edge -- east/west sides touch nothing, so they should read as
    # "buildable" (the UI's compass-edge simplification).
    responses.add(
        responses.POST, f"{BASE_URL}/{PARKS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"NAME": "Test Park"}, [[[0, 100], [0, 120], [100, 120], [100, 100], [0, 100]]]
        )]}, status=200,
    )
    responses.add(
        responses.POST, f"{BASE_URL}/{WETLANDS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"WETLAND_TYPE": "Lake"}, [[[0, -20], [0, 0], [100, 0], [100, -20], [0, -20]]]
        )]}, status=200,
    )
    for layer in (EASEMENTS_LAYER, COUNTY_PROPERTIES_LAYER, ROADS_LAYER):
        _empty_geom(layer)

    result = compute_boundary_features(SQUARE_PARCEL)

    assert result["edges"] == {"n": "park", "s": "water", "e": "buildable", "w": "buildable"}


@responses.activate
def test_compute_boundary_features_distinguishes_park_from_conservation_easement():
    responses.add(
        responses.POST, f"{BASE_URL}/{EASEMENTS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"ETYPE": "conservation"}, [[[0, 100], [0, 120], [100, 120], [100, 100], [0, 100]]]
        )]}, status=200,
    )
    for layer in (PARKS_LAYER, COUNTY_PROPERTIES_LAYER, WETLANDS_LAYER, ROADS_LAYER):
        _empty_geom(layer)

    result = compute_boundary_features(SQUARE_PARCEL)

    assert result["edges"]["n"] == "conservation"
    assert result["abuts_conservation_easement"] is True
    assert result["abuts_park_public"] is False


@responses.activate
def test_compute_boundary_features_fully_protected_has_no_buildable_edge():
    # park strip wraps the whole parcel -- nothing left over for
    # abuts_buildable_private.
    responses.add(
        responses.POST, f"{BASE_URL}/{PARKS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"NAME": "Big Park"}, [[[-20, -20], [-20, 120], [120, 120], [120, -20], [-20, -20]]]
        )]}, status=200,
    )
    for layer in (EASEMENTS_LAYER, COUNTY_PROPERTIES_LAYER, WETLANDS_LAYER, ROADS_LAYER):
        _empty_geom(layer)

    result = compute_boundary_features(SQUARE_PARCEL)

    assert result["abuts_buildable_private"] is False
    assert result["protected_perimeter_ratio"] == pytest.approx(1.0, abs=0.01)


@responses.activate
def test_wetland_pct_of_parcel_computes_overlap_area():
    # wetland polygon covers exactly the west half of the parcel
    responses.add(
        responses.POST, f"{BASE_URL}/{WETLANDS_LAYER}/query",
        json={"features": [_polygon_feature(
            {"WETLAND_TYPE": "Freshwater Emergent Wetland"},
            [[[0, 0], [0, 100], [50, 100], [50, 0], [0, 0]]],
        )]}, status=200,
    )

    result = wetland_pct_of_parcel(SQUARE_PARCEL)

    assert result == pytest.approx(0.5, abs=0.01)


@responses.activate
def test_wetland_pct_of_parcel_no_hits_is_zero():
    _empty_geom(WETLANDS_LAYER)

    assert wetland_pct_of_parcel(SQUARE_PARCEL) == 0.0


@responses.activate
def test_rear_open_distance_ft_measures_nearest_neighboring_footprint():
    own_building = _polygon_feature(
        {"Parcel_ID": "R001"}, [[[10, 10], [10, 20], [20, 20], [20, 10], [10, 10]]]
    )
    # neighbor footprint 30ft north of the subject building's north edge (y=20 -> y=50)
    neighbor_building = _polygon_feature(
        {"Parcel_ID": "R002"}, [[[10, 50], [10, 60], [20, 60], [20, 50], [10, 50]]]
    )
    responses.add(
        responses.POST, f"{BASE_URL}/{BUILDING_FOOTPRINTS_LAYER}/query",
        json={"features": [own_building, neighbor_building]}, status=200,
    )

    result = rear_open_distance_ft(SQUARE_PARCEL, "R001")

    assert result == pytest.approx(30.0, abs=0.01)


@responses.activate
def test_rear_open_distance_ft_none_when_subject_has_no_footprint():
    neighbor_building = _polygon_feature(
        {"Parcel_ID": "R002"}, [[[10, 50], [10, 60], [20, 60], [20, 50], [10, 50]]]
    )
    responses.add(
        responses.POST, f"{BASE_URL}/{BUILDING_FOOTPRINTS_LAYER}/query",
        json={"features": [neighbor_building]}, status=200,
    )

    assert rear_open_distance_ft(SQUARE_PARCEL, "R001") is None
