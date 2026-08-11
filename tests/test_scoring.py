import datetime as dt

from canopy.db.models import Listing, Parcel, Score
from canopy.scoring import old_growth_proxy_score, score_listings


def test_old_growth_proxy_score_none_when_missing_inputs():
    assert old_growth_proxy_score(None, 50.0) is None
    assert old_growth_proxy_score(1980, None) is None


def test_old_growth_proxy_score_combines_age_and_canopy():
    this_year = dt.date.today().year
    # 100-year-old house, 100% canopy -> max score of 1.0
    assert old_growth_proxy_score(this_year - 100, 100.0) == 1.0
    # brand new house, 0% canopy -> 0.0
    assert old_growth_proxy_score(this_year, 0.0) == 0.0
    # 50-year-old house, 50% canopy -> 0.5
    assert abs(old_growth_proxy_score(this_year - 50, 50.0) - 0.5) < 1e-9


def _make_listing_with_parcel(session, year_built=1970):
    listing = Listing(
        id="l1", formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=year_built, raw={},
    )
    parcel = Parcel(listing_id="l1", geometry_geojson={"type": "Polygon", "coordinates": []})
    session.add_all([listing, parcel])
    session.commit()
    return listing


def test_score_listings_persists_canopy_and_proxy(session, monkeypatch):
    listing = _make_listing_with_parcel(session, year_built=1970)
    monkeypatch.setattr("canopy.scoring.canopy_pct_for_geometry", lambda geom, crs: 60.0)

    results = score_listings(session, [listing])

    assert len(results) == 1
    score = session.query(Score).filter_by(listing_id="l1").one()
    assert score.canopy_pct == 60.0
    assert score.old_growth_proxy_score is not None


def test_score_listings_handles_no_parcel(session, monkeypatch):
    listing = Listing(
        id="l2", formatted_address="2 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active", raw={},
    )
    session.add(listing)
    session.commit()

    results = score_listings(session, [listing])

    assert len(results) == 1
    score = session.query(Score).filter_by(listing_id="l2").one()
    assert score.canopy_pct is None
    assert score.old_growth_proxy_score is None
