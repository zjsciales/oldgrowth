import requests

from canopy.db.models import Listing, ListingFeatures, Parcel, Score
from canopy.vision import CANOPY_OVERRIDE_CONFIDENCE_THRESHOLD, ensure_vision_features

FAKE_RESULT = {
    "arch_style": "coastal contemporary",
    "arch_style_confidence": 0.8,
    "exterior_material": "fiber cement",
    "has_front_porch": True,
    "garage_type": "attached",
    "visible_renovation_recency": "recent reno",
    "rationale": "Backs to marsh, 65% canopy.",
    "concerns": "",
    "canopy_condition": "consistent_with_raster",
    "canopy_condition_confidence": 0.9,
    "corrected_canopy_pct_estimate": 65.0,
    "house_lot_summary": "A coastal contemporary home with mature trees along the back of the lot.",
}


def _make_listing_and_features(session, photo_url=None):
    listing = Listing(
        id="l1", formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=1970, lot_size_sqft=20000, price=800000, raw={}, photo_url=photo_url,
    )
    parcel = Parcel(listing_id="l1", adjacent_water=True)
    score = Score(listing_id="l1", canopy_pct=65.0)
    features = ListingFeatures(
        listing_id="l1", feature_set_version="v1",
        parcel_canopy_pct=65.0, effective_canopy_pct=65.0, neighborhood_canopy_pct=70.0,
    )
    session.add_all([listing, parcel, score, features])
    session.commit()
    return listing, features


def test_ensure_vision_features_persists_result(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img, photo=None: FAKE_RESULT)

    result = ensure_vision_features(session, listing, features)

    assert result.arch_style == "coastal contemporary"
    assert result.has_front_porch is True
    assert result.vision_computed_at is not None
    assert result.house_lot_summary == FAKE_RESULT["house_lot_summary"]
    assert result.canopy_condition == "consistent_with_raster"
    assert result.vision_canopy_pct_estimate == 65.0
    score = session.query(Score).filter_by(listing_id="l1").one()
    assert "Backs to marsh" in score.subagent_rationale


def test_ensure_vision_features_appends_concerns_to_rationale(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    result_with_concern = {**FAKE_RESULT, "concerns": "a 'marsh' that looks like a retention pond"}
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr(
        "canopy.vision.extract_structural_features", lambda facts, img, photo=None: result_with_concern
    )

    ensure_vision_features(session, listing, features)

    score = session.query(Score).filter_by(listing_id="l1").one()
    assert "retention pond" in score.subagent_rationale


def test_ensure_vision_features_is_idempotent(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    call_count = 0

    def fake_extract(facts, img, photo=None):
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
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img, photo=None: FAKE_RESULT)

    result = ensure_vision_features(session, listing, features)

    assert result.arch_style == "coastal contemporary"


def test_ensure_vision_features_overrides_canopy_above_confidence_threshold(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    result = {
        **FAKE_RESULT,
        "canopy_condition": "recently_cleared",
        "canopy_condition_confidence": CANOPY_OVERRIDE_CONFIDENCE_THRESHOLD + 0.01,
        "corrected_canopy_pct_estimate": 5.0,
    }
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img, photo=None: result)

    updated = ensure_vision_features(session, listing, features)

    assert updated.effective_canopy_pct == 5.0
    assert updated.canopy_pct_overridden_by_vision is True
    # canopy_delta must be recomputed against the new effective value, not
    # left stale against the pre-override raster number -- otherwise the
    # feature vector becomes internally inconsistent (neighborhood(70) -
    # stale-raster(65) != neighborhood(70) - corrected(5)).
    assert updated.canopy_delta == 70.0 - 5.0


def test_ensure_vision_features_does_not_override_canopy_below_confidence_threshold(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    result = {
        **FAKE_RESULT,
        "canopy_condition": "recently_cleared",
        "canopy_condition_confidence": CANOPY_OVERRIDE_CONFIDENCE_THRESHOLD - 0.01,
        "corrected_canopy_pct_estimate": 5.0,
    }
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img, photo=None: result)

    updated = ensure_vision_features(session, listing, features)

    assert updated.effective_canopy_pct == 65.0  # unchanged from features.py's raster default
    assert updated.canopy_pct_overridden_by_vision is False
    # still recorded as an audit trail even though it wasn't applied
    assert updated.vision_canopy_pct_estimate == 5.0


def test_ensure_vision_features_does_not_override_when_consistent_even_at_high_confidence(session, monkeypatch):
    listing, features = _make_listing_and_features(session)
    result = {
        **FAKE_RESULT,
        "canopy_condition": "consistent_with_raster",
        "canopy_condition_confidence": 0.99,
        "corrected_canopy_pct_estimate": 60.0,
    }
    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"fake-image-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", lambda facts, img, photo=None: result)

    updated = ensure_vision_features(session, listing, features)

    assert updated.effective_canopy_pct == 65.0
    assert updated.canopy_pct_overridden_by_vision is False


def test_ensure_vision_features_fetches_listing_photo_when_present(session, monkeypatch):
    listing, features = _make_listing_and_features(session, photo_url="https://example.com/photo.jpg")
    captured = {}

    def fake_extract(facts, img, photo=None):
        captured["photo"] = photo
        return FAKE_RESULT

    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"satellite-bytes")
    monkeypatch.setattr("canopy.vision._fetch_listing_photo_bytes", lambda url: b"photo-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", fake_extract)

    ensure_vision_features(session, listing, features)

    assert captured["photo"] == b"photo-bytes"


def test_ensure_vision_features_no_photo_url_passes_none(session, monkeypatch):
    listing, features = _make_listing_and_features(session, photo_url=None)
    captured = {}

    def fake_extract(facts, img, photo=None):
        captured["photo"] = photo
        return FAKE_RESULT

    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"satellite-bytes")
    monkeypatch.setattr("canopy.vision.extract_structural_features", fake_extract)

    ensure_vision_features(session, listing, features)

    assert captured["photo"] is None


def test_fetch_listing_photo_bytes_falls_back_to_none_on_request_error(session, monkeypatch):
    listing, features = _make_listing_and_features(session, photo_url="https://example.com/photo.jpg")
    captured = {}

    def fake_extract(facts, img, photo=None):
        captured["photo"] = photo
        return FAKE_RESULT

    def raise_request_error(*args, **kwargs):
        raise requests.RequestException("boom")

    monkeypatch.setattr("canopy.vision.fetch_satellite_image", lambda lat, lon: b"satellite-bytes")
    monkeypatch.setattr("canopy.vision.requests.get", raise_request_error)
    monkeypatch.setattr("canopy.vision.extract_structural_features", fake_extract)

    ensure_vision_features(session, listing, features)  # must not raise

    assert captured["photo"] is None
