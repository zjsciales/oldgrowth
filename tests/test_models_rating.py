"""Round-trip tests for the preference-layer tables added in the rating
pivot (see docs/FEATURE_SCHEMA.md). Seed-data correctness (23 tags, 2
raters) is verified against the real migration/Postgres, not here --
this sqlite fixture builds schema from models.py only, no migration
data-seeding runs against it."""

from canopy.db.models import (
    Anchor,
    Judgment,
    JudgmentAnchor,
    JudgmentTag,
    Listing,
    ListingAnchorTime,
    ListingFeatures,
    ModelRun,
    PairwiseComparison,
    PreferenceScore,
    Rater,
    Tag,
)


def _listing(listing_id: str = "l1") -> Listing:
    return Listing(
        id=listing_id, formatted_address="1 Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9,
        status="Active", price=500000, raw={},
    )


def test_listing_features_round_trip(session):
    session.add(_listing())
    session.add(ListingFeatures(
        listing_id="l1", feature_set_version="v1",
        lot_acreage=0.5, protected_perimeter_ratio=0.4,
        abuts_water=True, parcel_canopy_pct=70.0,
        imputed_fields=["median_year_built_buffer"], extra={},
    ))
    session.commit()

    row = session.query(ListingFeatures).filter_by(listing_id="l1").one()
    assert row.feature_set_version == "v1"
    assert row.protected_perimeter_ratio == 0.4
    assert row.abuts_water is True
    assert row.imputed_fields == ["median_year_built_buffer"]


def test_rater_and_anchor_round_trip(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    anchor = Anchor(
        label="Wrightsville Beach", category="beach", lat=34.2, lon=-77.8,
        ideal_minutes=15, limit_minutes=25, created_by="zach",
    )
    session.add(anchor)
    session.commit()

    saved = session.query(Anchor).filter_by(label="Wrightsville Beach").one()
    assert saved.created_by == "zach"
    assert saved.active is True


def test_listing_anchor_time_round_trip(session):
    session.add(_listing())
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(Anchor(
        label="Grocery", category="grocery", lat=34.2, lon=-77.8,
        created_by="zach",
    ))
    session.commit()
    anchor_id = session.query(Anchor).one().id

    session.add(ListingAnchorTime(
        listing_id="l1", anchor_id=anchor_id, drive_minutes=8.2,
        straight_line_km=4.1, is_proxy=True,
    ))
    session.commit()

    row = session.query(ListingAnchorTime).filter_by(listing_id="l1").one()
    assert row.is_proxy is True
    assert row.drive_minutes == 8.2


def test_judgment_with_tags_and_anchor_attribution(session):
    session.add(_listing())
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(Tag(
        code="mature_canopy", label="Beautiful trees on the lot",
        polarity="positive", mapped_features=["parcel_canopy_pct"],
    ))
    session.add(Tag(
        code="well_placed", label="Well placed for us", polarity="positive",
        mapped_features=["anchor_drive_times"], anchor_aware=True,
    ))
    session.add(Anchor(
        label="The Robertsons", category="social", lat=34.2, lon=-77.8,
        created_by="zach",
    ))
    session.commit()
    anchor_id = session.query(Anchor).one().id

    judgment = Judgment(
        rater_id="zach", listing_id="l1", mode="swipe", verdict="yes",
        session_id="s1", feature_set_version="v1",
    )
    session.add(judgment)
    session.commit()

    session.add(JudgmentTag(judgment_id=judgment.id, tag_code="mature_canopy"))
    session.add(JudgmentTag(judgment_id=judgment.id, tag_code="well_placed"))
    session.add(JudgmentAnchor(judgment_id=judgment.id, anchor_id=anchor_id))
    session.commit()

    tag_codes = {
        row.tag_code for row in
        session.query(JudgmentTag).filter_by(judgment_id=judgment.id)
    }
    assert tag_codes == {"mature_canopy", "well_placed"}
    assert session.query(JudgmentAnchor).filter_by(judgment_id=judgment.id).count() == 1


def test_pairwise_comparison_round_trip(session):
    session.add(_listing("l1"))
    session.add(_listing("l2"))
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    session.add(PairwiseComparison(
        rater_id="zach", listing_a="l1", listing_b="l2", winner="a",
        selection_strategy="active", feature_set_version="v1",
    ))
    session.commit()

    row = session.query(PairwiseComparison).one()
    assert row.winner == "a"


def test_model_run_and_preference_score_round_trip(session):
    session.add(_listing())
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    model_run = ModelRun(
        rater_id="zach", feature_set_version="v1", n_pairs=0,
        coefficients={"parcel_canopy_pct": 0.8}, scaler_params={},
    )
    session.add(model_run)
    session.commit()

    session.add(PreferenceScore(
        listing_id="l1", model_run_id=model_run.id,
        raw_score=1.2, display_score=87.0, pred_variance=0.03,
    ))
    session.commit()

    row = session.query(PreferenceScore).filter_by(listing_id="l1").one()
    assert row.model_run_id == model_run.id
    assert row.display_score == 87.0
