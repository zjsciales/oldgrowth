from canopy.db.models import Listing, ListingFeatures, Parcel, Score
from canopy.vision import ensure_vision_features

FAKE_RESULT = {
    "arch_style": "coastal contemporary",
    "arch_style_confidence": 0.8,
    "exterior_material": "fiber cement",
    "has_front_porch": True,
    "garage_type": "attached",
    "visible_renovation_recency": "recent reno",
    "rationale": "Backs to marsh, 65% canopy.",
    "concerns": "",
}


def _make_listing_and_features(session):
    listing = Listing(
        id="l1", formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=1970, lot_size_sqft=20000, price=800000, raw={},
    )
    parcel = Parcel(listing_id="l1", adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=65.0)
    features = ListingFeatures(listing_id="l1", feature_set_version="v1", parcel_canopy_pct=65.0)
    session.add_all([listing, parcel, score, features])
    session.commit()
    return listing, features


def test_ensure_vision_features_persists_result(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img: FAKE_RESULT)

    result = ensure_vision_features(session, listing, features)

    assert result.arch_style == "coastal contemporary"
    assert result.has_front_porch is True
    assert result.vision_computed_at is not None
    score = session.query(Score).filter_by(listing_id="l1").one()
    assert "Backs to marsh" in score.subagent_rationale


def test_ensure_vision_features_appends_concerns_to_rationale(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    result_with_concern = {**FAKE_RESULT, "concerns": "possible recent clearing on north edge"}
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img: result_with_concern)

    ensure_vision_features(session, listing, features)

    score = session.query(Score).filter_by(listing_id="l1").one()
    assert "possible recent clearing" in score.subagent_rationale


def test_ensure_vision_features_is_idempotent(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    call_count = 0

    def fake_extract(facts, img):
        nonlocal call_count
        call_count += 1
        return FAKE_RESULT

    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", fake_extract)

    ensure_vision_features(session, listing, features)
    ensure_vision_features(session, listing, features)  # already computed -- must not re-call Claude/Mapbox

    assert call_count == 1


def test_ensure_vision_features_skips_missing_score_gracefully(session, monkeypatch):
    listing = Listing(
        id="l2", formatted_address="2 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active", raw={},
    )
    features = ListingFeatures(listing_id="l2", feature_set_version="v1")
    session.add_all([listing, features])
    session.commit()
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img: FAKE_RESULT)

    result = ensure_vision_features(session, listing, features)

    assert result.arch_style == "coastal contemporary"
