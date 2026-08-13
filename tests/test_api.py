import json

from canopy.app import app
from canopy.db.models import Listing, ListingFeatures, ModelRun, Rater, Tag


def _listing(listing_id="l1", **overrides):
    defaults = dict(
        id=listing_id, formatted_address=f"{listing_id} Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        price=500000, raw={},
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _features(listing_id="l1", **overrides):
    defaults = dict(listing_id=listing_id, feature_set_version="v1", parcel_canopy_pct=60.0)
    defaults.update(overrides)
    return ListingFeatures(**defaults)


def _client(monkeypatch, session):
    monkeypatch.setattr("canopy.api.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.api.ensure_vision_features", lambda session_, listing, features: features)
    return app.test_client()


def test_tags_returns_seeded_taxonomy(monkeypatch, session):
    session.add(Tag(code="mature_canopy", label="Beautiful trees", polarity="positive", mapped_features=["parcel_canopy_pct"]))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.get("/api/tags")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["tags"][0]["code"] == "mature_canopy"
    assert body["tags"][0]["mappedFeatures"] == ["parcel_canopy_pct"]


def test_location_map_returns_image_with_long_cache_header(monkeypatch, session):
    session.add(_listing("l1"))
    session.commit()
    monkeypatch.setattr("canopy.api.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.api.fetch_location_map", lambda lat, lon, **kw: b"fake-png-bytes")
    client = app.test_client()

    resp = client.get("/api/listings/l1/location-map")

    assert resp.status_code == 200
    assert resp.data == b"fake-png-bytes"
    assert resp.mimetype == "image/png"
    assert "max-age=31536000" in resp.headers["Cache-Control"]


def test_location_map_404s_for_unknown_listing(monkeypatch, session):
    monkeypatch.setattr("canopy.api.SessionLocal", lambda: session)
    client = app.test_client()

    resp = client.get("/api/listings/nope/location-map")

    assert resp.status_code == 404


def test_location_map_502s_on_mapbox_failure(monkeypatch, session):
    from canopy.clients.mapbox import MapboxError

    session.add(_listing("l1"))
    session.commit()
    monkeypatch.setattr("canopy.api.SessionLocal", lambda: session)

    def _raise(lat, lon, **kw):
        raise MapboxError("boom")

    monkeypatch.setattr("canopy.api.fetch_location_map", _raise)
    client = app.test_client()

    resp = client.get("/api/listings/l1/location-map")

    assert resp.status_code == 502


def test_batch_requires_rater(monkeypatch, session):
    client = _client(monkeypatch, session)

    resp = client.get("/api/batch")

    assert resp.status_code == 400


def test_batch_returns_listing_cards(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(_listing("l1"))
    session.add(_features(
        "l1", lot_acreage=0.5, is_tract_new_build=True,
        extra={"edges": {"n": "water", "e": "buildable", "s": "buildable", "w": "buildable"}},
    ))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.get("/api/batch?rater=zach&n=5")

    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["listings"]) == 1
    card = body["listings"][0]
    assert card["id"] == "l1"
    assert card["parcelCanopy"] == 60
    assert card["edges"]["n"] == "water"
    assert card["drives"] == {}
    assert "google.com/search?q=%22l1%20Test%20St%22" in card["searchUrl"]
    assert "34.1,-77.9" in card["satelliteUrl"]
    assert card["countyRecordsUrl"] == "https://tax.nhcgov.com/436/Records-Search"
    assert card["parcelId"] is None
    assert card["isTractNewBuild"] is True


def test_batch_caps_synchronous_vision_calls(monkeypatch, session):
    """A batch full of never-viewed listings must not fire a vision call
    per listing -- that's the exact scenario that blew past gunicorn's
    worker timeout on the first real Railway load (40 sequential
    Anthropic calls in one request). All listings still come back as
    cards; only the first MAX_VISION_CALLS_PER_BATCH trigger vision."""
    session.add(Rater(id="zach", display_name="Zach"))
    n_listings = 10
    for i in range(n_listings):
        session.add(_listing(f"l{i}"))
        session.add(_features(f"l{i}"))
    session.commit()

    calls = []
    monkeypatch.setattr("canopy.api.SessionLocal", lambda: session)
    monkeypatch.setattr(
        "canopy.api.ensure_vision_features",
        lambda session_, listing, features: calls.append(listing.id) or features,
    )
    client = app.test_client()

    resp = client.get(f"/api/batch?rater=zach&n={n_listings}")

    assert resp.status_code == 200
    body = resp.get_json()
    assert len(body["listings"]) == n_listings
    from canopy.api import MAX_VISION_CALLS_PER_BATCH
    assert len(calls) == MAX_VISION_CALLS_PER_BATCH


def test_pair_returns_two_cards_and_strategy(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.add_all([_features("l1"), _features("l2")])
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.get("/api/pair?rater=zach")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["selection_strategy"] == "random"
    assert {body["listing_a"]["id"], body["listing_b"]["id"]} == {"l1", "l2"}


def test_pair_returns_400_when_not_enough_listings(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    client = _client(monkeypatch, session)

    resp = client.get("/api/pair?rater=zach")

    assert resp.status_code == 400


def test_judgment_creates_and_validates(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(Tag(code="mature_canopy", label="Beautiful trees", polarity="positive", mapped_features=[]))
    session.add(_listing("l1"))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.post(
        "/api/judgment",
        data=json.dumps({
            "rater_id": "zach", "listing_id": "l1", "mode": "swipe", "verdict": "yes",
            "session_id": "s1", "tags": ["mature_canopy"],
        }),
        content_type="application/json",
    )

    assert resp.status_code == 201
    assert "id" in resp.get_json()


def test_judgment_returns_400_on_invalid_verdict(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(_listing("l1"))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.post(
        "/api/judgment",
        data=json.dumps({"rater_id": "zach", "listing_id": "l1", "mode": "swipe", "verdict": "bogus", "session_id": "s1"}),
        content_type="application/json",
    )

    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_comparison_creates(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add_all([_listing("l1"), _listing("l2")])
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.post(
        "/api/comparison",
        data=json.dumps({"rater_id": "zach", "listing_a": "l1", "listing_b": "l2", "winner": "a"}),
        content_type="application/json",
    )

    assert resp.status_code == 201


def test_weights_not_enough_data(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.get("/api/weights?rater=zach")

    assert resp.status_code == 200
    assert resp.get_json()["status"] == "not_enough_data"


def test_weights_returns_latest_model_run(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()
    session.add(ModelRun(
        rater_id="zach", feature_set_version="v1", n_pairs=42,
        coefficients={"parcel_canopy_pct": 0.8}, scaler_params={}, holdout_accuracy=0.7,
    ))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.get("/api/weights?rater=zach")

    body = resp.get_json()
    assert body["status"] == "ok"
    assert body["n_pairs"] == 42
    assert body["coefficients"]["parcel_canopy_pct"] == 0.8


def test_weights_includes_tag_stats_even_without_a_fitted_model(monkeypatch, session):
    from canopy.rating import record_judgment

    session.add(Rater(id="zach", display_name="Zach"))
    session.add(Tag(code="mature_canopy", label="Trees", polarity="positive", mapped_features=["parcel_canopy_pct"]))
    session.add(_listing("l1"))
    session.commit()
    record_judgment(session, rater_id="zach", listing_id="l1", mode="swipe", verdict="yes", session_id="s1", tags=["mature_canopy"])
    client = _client(monkeypatch, session)

    resp = client.get("/api/weights?rater=zach")

    body = resp.get_json()
    assert body["status"] == "not_enough_data"
    assert body["tagStats"]["parcel_canopy_pct"]["credit"] == 1
    assert body["tagStats"]["parcel_canopy_pct"]["blame"] == 0


def test_anchors_full_crud(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()
    client = _client(monkeypatch, session)

    create_resp = client.post(
        "/api/anchors",
        data=json.dumps({"label": "Grocery", "category": "grocery", "created_by": "zach", "lat": 34.2, "lon": -77.8}),
        content_type="application/json",
    )
    assert create_resp.status_code == 201
    anchor_id = create_resp.get_json()["id"]

    list_resp = client.get("/api/anchors")
    assert len(list_resp.get_json()["anchors"]) == 1

    update_resp = client.patch(
        f"/api/anchors/{anchor_id}",
        data=json.dumps({"ideal": 5}),
        content_type="application/json",
    )
    assert update_resp.status_code == 200
    assert update_resp.get_json()["ideal"] == 5

    delete_resp = client.delete(f"/api/anchors/{anchor_id}")
    assert delete_resp.status_code == 204
    assert client.get("/api/anchors").get_json()["anchors"] == []


def test_anchors_create_requires_lat_lon_or_address(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()
    client = _client(monkeypatch, session)

    resp = client.post(
        "/api/anchors",
        data=json.dumps({"label": "Nowhere", "category": "work", "created_by": "zach"}),
        content_type="application/json",
    )

    assert resp.status_code == 400


def test_anchors_update_404_for_missing(monkeypatch, session):
    client = _client(monkeypatch, session)

    resp = client.patch("/api/anchors/999", data=json.dumps({"ideal": 5}), content_type="application/json")

    assert resp.status_code == 404
