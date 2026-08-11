from canopy.app import app
from canopy.db.models import Listing, Parcel, Score


def test_healthz():
    client = app.test_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json() == {"status": "ok"}


def test_listings_empty_state(monkeypatch, session):
    monkeypatch.setattr("canopy.app.SessionLocal", lambda: session)
    client = app.test_client()

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"No listings have met the criteria yet" in resp.data


def test_listings_shows_passed_candidates(monkeypatch, session):
    listing = Listing(
        id="l1", formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=1970, lot_size_sqft=20000, price=800000, raw={},
    )
    parcel = Parcel(listing_id="l1", parcel_id="R12345", adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=65.0, passed_filter=True, subagent_rationale="Backs to marsh.")
    session.add_all([listing, parcel, score])
    session.commit()

    monkeypatch.setattr("canopy.app.SessionLocal", lambda: session)
    client = app.test_client()

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"1 Test St" in resp.data
    assert b"Backs to marsh" in resp.data
    assert b"Water adjacent" in resp.data
