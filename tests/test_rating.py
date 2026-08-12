import pytest

from canopy.db.models import (
    Anchor,
    JudgmentAnchor,
    JudgmentTag,
    Listing,
    ListingFeatures,
    ModelRun,
    PairwiseComparison,
    PreferenceScore,
    Rater,
    Tag,
)
from canopy.rating import (
    RatingValidationError,
    create_anchor,
    delete_anchor,
    ensure_anchor_times,
    get_batch,
    get_pair,
    list_anchors,
    record_comparison,
    record_judgment,
    update_anchor,
)


def _listing(listing_id, **overrides):
    defaults = dict(
        id=listing_id, formatted_address=f"{listing_id} Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        price=500000, raw={},
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _features(listing_id, **overrides):
    defaults = dict(listing_id=listing_id, feature_set_version="v1")
    defaults.update(overrides)
    return ListingFeatures(**defaults)


def _seed_common(session):
    session.add_all([
        Rater(id="zach", display_name="Zach"),
        Tag(code="mature_canopy", label="Beautiful trees", polarity="positive", mapped_features=["parcel_canopy_pct"]),
        Tag(code="lot_too_open", label="Lot too open", polarity="negative", mapped_features=["parcel_canopy_pct"]),
        Tag(code="well_placed", label="Well placed", polarity="positive", mapped_features=["anchor_drive_times"], anchor_aware=True),
    ])
    session.commit()


# ---------------------------------------------------------------------------
# record_judgment
# ---------------------------------------------------------------------------


def test_record_judgment_persists_tags(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.commit()

    judgment = record_judgment(
        session, rater_id="zach", listing_id="l1", mode="swipe", verdict="yes",
        session_id="s1", tags=["mature_canopy"],
    )

    assert judgment.id is not None
    tag_codes = {jt.tag_code for jt in session.query(JudgmentTag).filter_by(judgment_id=judgment.id)}
    assert tag_codes == {"mature_canopy"}


def test_record_judgment_rejects_invalid_mode(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.commit()

    with pytest.raises(RatingValidationError):
        record_judgment(session, rater_id="zach", listing_id="l1", mode="bogus", verdict="yes", session_id="s1")


def test_record_judgment_rejects_invalid_verdict(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.commit()

    with pytest.raises(RatingValidationError):
        record_judgment(session, rater_id="zach", listing_id="l1", mode="swipe", verdict="bogus", session_id="s1")


def test_record_judgment_rejects_wrong_polarity_tag(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.commit()

    # lot_too_open is a negative tag -- shouldn't be attachable to a "yes"
    with pytest.raises(RatingValidationError):
        record_judgment(
            session, rater_id="zach", listing_id="l1", mode="swipe", verdict="yes",
            session_id="s1", tags=["lot_too_open"],
        )


def test_record_judgment_rejects_unknown_tag(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.commit()

    with pytest.raises(RatingValidationError):
        record_judgment(
            session, rater_id="zach", listing_id="l1", mode="swipe", verdict="yes",
            session_id="s1", tags=["not_a_real_tag"],
        )


def test_record_judgment_maybe_cannot_carry_tags(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.commit()

    with pytest.raises(RatingValidationError):
        record_judgment(
            session, rater_id="zach", listing_id="l1", mode="swipe", verdict="maybe",
            session_id="s1", tags=["mature_canopy"],
        )


def test_record_judgment_with_anchor_attribution(session):
    _seed_common(session)
    session.add(_listing("l1"))
    session.add(Anchor(label="The Robertsons", category="social", lat=34.2, lon=-77.8, created_by="zach"))
    session.commit()
    anchor_id = session.query(Anchor).one().id

    judgment = record_judgment(
        session, rater_id="zach", listing_id="l1", mode="swipe", verdict="yes",
        session_id="s1", tags=["well_placed"], anchor_ids=[anchor_id],
    )

    attributed = session.query(JudgmentAnchor).filter_by(judgment_id=judgment.id).all()
    assert len(attributed) == 1
    assert attributed[0].anchor_id == anchor_id


def test_record_judgment_free_text_attaches_to_other_tag_only(session):
    session.add_all([
        Rater(id="zach", display_name="Zach"),
        Tag(code="mature_canopy", label="Beautiful trees", polarity="positive", mapped_features=[]),
        Tag(code="other_yes", label="Something else", polarity="positive", mapped_features=[]),
    ])
    session.add(_listing("l1"))
    session.commit()

    judgment = record_judgment(
        session, rater_id="zach", listing_id="l1", mode="detail", verdict="yes", session_id="s1",
        tags=["mature_canopy", "other_yes"], free_text="loved the old oak tree",
    )

    rows = {jt.tag_code: jt.free_text for jt in session.query(JudgmentTag).filter_by(judgment_id=judgment.id)}
    assert rows["other_yes"] == "loved the old oak tree"
    assert rows["mature_canopy"] is None


# ---------------------------------------------------------------------------
# record_comparison
# ---------------------------------------------------------------------------


def test_record_comparison_persists(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.commit()

    comparison = record_comparison(session, rater_id="zach", listing_a="l1", listing_b="l2", winner="a")

    assert comparison.id is not None
    saved = session.query(PairwiseComparison).one()
    assert saved.winner == "a"


def test_record_comparison_rejects_invalid_winner(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.commit()

    with pytest.raises(RatingValidationError):
        record_comparison(session, rater_id="zach", listing_a="l1", listing_b="l2", winner="bogus")


# ---------------------------------------------------------------------------
# get_batch / get_pair
# ---------------------------------------------------------------------------


def test_get_batch_cold_start_excludes_already_judged(session):
    session.add(Rater(id="zach", display_name="Zach"))
    for i in range(5):
        session.add(_listing(f"l{i}", price=400000 + i * 10000))
        session.add(_features(f"l{i}", parcel_canopy_pct=float(i * 10), lot_acreage=0.5))
    session.commit()
    record_judgment(session, rater_id="zach", listing_id="l0", mode="swipe", verdict="yes", session_id="s1")

    batch = get_batch(session, "zach", n=10)

    assert "l0" not in {listing.id for listing in batch}
    assert len(batch) == 4


def test_get_batch_post_model_orders_by_pred_variance(session):
    session.add(Rater(id="zach", display_name="Zach"))
    for i in range(3):
        session.add(_listing(f"l{i}"))
        session.add(_features(f"l{i}"))
    model_run = ModelRun(rater_id="zach", feature_set_version="v1", n_pairs=50, coefficients={}, scaler_params={})
    session.add(model_run)
    session.commit()
    session.add_all([
        PreferenceScore(listing_id="l0", model_run_id=model_run.id, raw_score=0.1, display_score=10, pred_variance=0.9),
        PreferenceScore(listing_id="l1", model_run_id=model_run.id, raw_score=0.2, display_score=20, pred_variance=0.1),
        PreferenceScore(listing_id="l2", model_run_id=model_run.id, raw_score=0.3, display_score=30, pred_variance=0.5),
    ])
    session.commit()

    batch = get_batch(session, "zach", n=3)

    assert [listing.id for listing in batch] == ["l0", "l2", "l1"]


def test_get_pair_cold_start_returns_random_strategy(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.add_all([_features("l1"), _features("l2")])
    session.commit()

    a, b, strategy = get_pair(session, "zach")

    assert strategy == "random"
    assert {a.id, b.id} == {"l1", "l2"}


def test_get_pair_raises_when_not_enough_listings(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(_listing("l1"))
    session.add(_features("l1"))
    session.commit()

    with pytest.raises(RatingValidationError):
        get_pair(session, "zach")


def test_get_pair_post_model_picks_smallest_score_gap(session):
    session.add(Rater(id="zach", display_name="Zach"))
    for i in range(3):
        session.add(_listing(f"l{i}"))
        session.add(_features(f"l{i}"))
    model_run = ModelRun(rater_id="zach", feature_set_version="v1", n_pairs=50, coefficients={}, scaler_params={})
    session.add(model_run)
    session.commit()
    session.add_all([
        PreferenceScore(listing_id="l0", model_run_id=model_run.id, raw_score=0.0, display_score=10, pred_variance=0.1),
        PreferenceScore(listing_id="l1", model_run_id=model_run.id, raw_score=0.05, display_score=15, pred_variance=0.1),
        PreferenceScore(listing_id="l2", model_run_id=model_run.id, raw_score=5.0, display_score=90, pred_variance=0.1),
    ])
    session.commit()

    a, b, strategy = get_pair(session, "zach")

    assert strategy == "active"
    assert {a.id, b.id} == {"l0", "l1"}  # smallest raw_score gap


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------


def test_create_anchor_with_direct_coordinates(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    anchor = create_anchor(
        session, label="Wrightsville Beach", category="beach", created_by="zach", lat=34.2, lon=-77.8,
    )

    assert anchor.id is not None
    assert anchor.ideal_minutes == 15
    assert anchor.limit_minutes == 30


def test_create_anchor_geocodes_address(session, monkeypatch):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()
    monkeypatch.setattr("canopy.rating.geocode_address", lambda q: (34.5, -77.5))

    anchor = create_anchor(session, label="Work", category="work", created_by="zach", address="123 Main St")

    assert anchor.lat == 34.5
    assert anchor.lon == -77.5


def test_create_anchor_raises_when_geocoding_fails(session, monkeypatch):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()
    monkeypatch.setattr("canopy.rating.geocode_address", lambda q: None)

    with pytest.raises(RatingValidationError):
        create_anchor(session, label="Nowhere", category="work", created_by="zach", address="nonsense")


def test_create_anchor_requires_lat_lon_or_address(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    with pytest.raises(RatingValidationError):
        create_anchor(session, label="Somewhere", category="work", created_by="zach")


def test_update_and_delete_anchor(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(Anchor(label="Grocery", category="grocery", lat=34.2, lon=-77.8, created_by="zach"))
    session.commit()
    anchor_id = session.query(Anchor).one().id

    updated = update_anchor(session, anchor_id, ideal_minutes=10)
    assert updated.ideal_minutes == 10

    delete_anchor(session, anchor_id)
    assert list_anchors(session) == []
    assert list_anchors(session, include_inactive=True)[0].active is False


def test_update_anchor_raises_for_missing_anchor(session):
    with pytest.raises(RatingValidationError):
        update_anchor(session, 999, ideal_minutes=5)


# ---------------------------------------------------------------------------
# ensure_anchor_times
# ---------------------------------------------------------------------------


def test_ensure_anchor_times_computes_haversine_proxy(session):
    session.add(Rater(id="zach", display_name="Zach"))
    listing = _listing("l1", latitude=34.20, longitude=-77.90)
    session.add(listing)
    # ~0.111 km per 0.001 degree latitude -- a small, known offset
    session.add(Anchor(label="Grocery", category="grocery", lat=34.201, lon=-77.90, created_by="zach"))
    session.commit()

    result = ensure_anchor_times(session, listing)

    anchor_id = session.query(Anchor).one().id
    assert anchor_id in result
    row = result[anchor_id]
    assert row.is_proxy is True
    assert row.straight_line_km == pytest.approx(0.111, abs=0.01)
    assert row.drive_minutes == pytest.approx(row.straight_line_km / 0.55, abs=0.01)


def test_ensure_anchor_times_is_idempotent(session):
    session.add(Rater(id="zach", display_name="Zach"))
    listing = _listing("l1")
    session.add(listing)
    session.add(Anchor(label="Grocery", category="grocery", lat=34.2, lon=-77.8, created_by="zach"))
    session.commit()

    first = ensure_anchor_times(session, listing)
    second = ensure_anchor_times(session, listing)

    assert first.keys() == second.keys()
    from canopy.db.models import ListingAnchorTime
    assert session.query(ListingAnchorTime).count() == 1


def test_ensure_anchor_times_skips_inactive_anchors(session):
    session.add(Rater(id="zach", display_name="Zach"))
    listing = _listing("l1")
    session.add(listing)
    session.add(Anchor(label="Old Place", category="grocery", lat=34.2, lon=-77.8, created_by="zach", active=False))
    session.commit()

    result = ensure_anchor_times(session, listing)

    assert result == {}
