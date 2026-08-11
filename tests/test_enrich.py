from canopy.db.models import Listing, Parcel
from canopy.enrich import enrich_listings

FAKE_GIS_RESULT = {
    "parcel_id": "R05511-999-001-000",
    "geometry_geojson": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    "adjacent_water": True,
    "adjacent_park_or_conservation": False,
    "adjacent_county_or_city_owned": False,
    "flood_zone": "X",
    "wetland_overlay": False,
    "raw_gis": {"parcel_attributes": {}},
}


def _make_listing(session, listing_id="l1"):
    listing = Listing(
        id=listing_id, formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active", raw={},
    )
    session.add(listing)
    session.commit()
    return listing


def test_enrich_listings_creates_parcel(session, monkeypatch):
    listing = _make_listing(session)
    monkeypatch.setattr("canopy.enrich.enrich_parcel", lambda lat, lon: FAKE_GIS_RESULT)

    results = enrich_listings(session, [listing])

    assert len(results) == 1
    parcel = session.query(Parcel).filter_by(listing_id="l1").one()
    assert parcel.parcel_id == "R05511-999-001-000"
    assert parcel.adjacent_water is True


def test_enrich_listings_updates_existing_parcel(session, monkeypatch):
    listing = _make_listing(session)
    monkeypatch.setattr("canopy.enrich.enrich_parcel", lambda lat, lon: FAKE_GIS_RESULT)
    enrich_listings(session, [listing])

    updated_result = {**FAKE_GIS_RESULT, "flood_zone": "AE"}
    monkeypatch.setattr("canopy.enrich.enrich_parcel", lambda lat, lon: updated_result)
    enrich_listings(session, [listing])

    assert session.query(Parcel).filter_by(listing_id="l1").count() == 1
    parcel = session.query(Parcel).filter_by(listing_id="l1").one()
    assert parcel.flood_zone == "AE"
