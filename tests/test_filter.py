from canopy.db.models import Listing, Parcel, Score
from canopy.filter import evaluate_listing, filter_listings


def _listing(lot_size=20000):
    return Listing(
        id="l1", formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        lot_size_sqft=lot_size, raw={},
    )


def _parcel(**kwargs):
    defaults = dict(
        listing_id="l1", adjacent_water=False, adjacent_park_or_conservation=False,
        adjacent_county_or_city_owned=False, wetland_overlay=False,
    )
    defaults.update(kwargs)
    return Parcel(**defaults)


def test_evaluate_listing_passes_when_all_thresholds_met():
    listing = _listing(lot_size=20000)
    parcel = _parcel(adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=60.0)

    passed, reasons = evaluate_listing(listing, parcel, score)

    assert passed is True
    assert reasons == {"lot_size_ok": True, "canopy_pct_ok": True, "adjacency_ok": True}


def test_evaluate_listing_fails_on_small_lot():
    listing = _listing(lot_size=5000)
    parcel = _parcel(adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=60.0)

    passed, reasons = evaluate_listing(listing, parcel, score)

    assert passed is False
    assert reasons["lot_size_ok"] is False


def test_evaluate_listing_fails_without_adjacency_flag():
    listing = _listing(lot_size=20000)
    parcel = _parcel()  # no adjacency flags set
    score = Score(listing_id="l1", canopy_pct=60.0)

    passed, reasons = evaluate_listing(listing, parcel, score)

    assert passed is False
    assert reasons["adjacency_ok"] is False


def test_evaluate_listing_fails_with_no_parcel():
    listing = _listing(lot_size=20000)
    score = Score(listing_id="l1", canopy_pct=60.0)

    passed, reasons = evaluate_listing(listing, None, score)

    assert passed is False
    assert reasons["adjacency_ok"] is False


def test_filter_listings_persists_result_and_returns_candidates(session):
    listing = _listing(lot_size=20000)
    parcel = _parcel(adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=60.0)
    session.add_all([listing, parcel, score])
    session.commit()

    candidates = filter_listings(session, [listing])

    assert candidates == [listing]
    refreshed = session.query(Score).filter_by(listing_id="l1").one()
    assert refreshed.passed_filter is True
    assert refreshed.filter_reasons["lot_size_ok"] is True


def test_filter_listings_skips_unscored_listings(session):
    listing = _listing(lot_size=20000)
    session.add(listing)
    session.commit()

    candidates = filter_listings(session, [listing])

    assert candidates == []
