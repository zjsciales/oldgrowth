from canopy.db.models import Listing, Parcel, Score
from canopy.subagent import run_subagent_on_candidates

FAKE_RESULT = {"flag_ok": True, "rationale": "Backs to marsh, 65% canopy.", "concerns": ""}


def _make_listing(session):
    listing = Listing(
        id="l1", formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=1970, lot_size_sqft=20000, price=800000, raw={},
    )
    parcel = Parcel(listing_id="l1", adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=65.0, passed_filter=True)
    session.add_all([listing, parcel, score])
    session.commit()
    return listing


def test_run_subagent_on_candidates_persists_result(session, monkeypatch):
    listing = _make_listing(session)
    monkeypatch.setattr("canopy.subagent.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.subagent.evaluate_candidate", lambda facts, img: FAKE_RESULT)

    results = run_subagent_on_candidates(session, [listing])

    assert len(results) == 1
    score = session.query(Score).filter_by(listing_id="l1").one()
    assert score.subagent_flag_ok is True
    assert "Backs to marsh" in score.subagent_rationale


def test_run_subagent_appends_concerns_to_rationale(session, monkeypatch):
    listing = _make_listing(session)
    result_with_concern = {**FAKE_RESULT, "concerns": "possible recent clearing on north edge"}
    monkeypatch.setattr("canopy.subagent.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.subagent.evaluate_candidate", lambda facts, img: result_with_concern)

    run_subagent_on_candidates(session, [listing])

    score = session.query(Score).filter_by(listing_id="l1").one()
    assert "possible recent clearing" in score.subagent_rationale


def test_run_subagent_skips_unscored_listings(session, monkeypatch):
    listing = Listing(
        id="l2", formatted_address="2 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active", raw={},
    )
    session.add(listing)
    session.commit()

    results = run_subagent_on_candidates(session, [listing])

    assert results == []
