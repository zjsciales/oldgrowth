import datetime as dt

from shapely.geometry import Polygon, mapping

from canopy.db.models import Anchor, Listing, ListingAnchorTime, ListingFeatures, Parcel, Rater, Score
from canopy.features import (
    FEATURE_SET_VERSION,
    _haversine_ft,
    _market_fields,
    _median_year_built_buffer,
    anchor_rollups,
    compute_feature_vector,
    compute_features_for_listings,
)

SQUARE_PARCEL = Polygon([(0, 0), (0, 208.7), (208.7, 208.7), (208.7, 0), (0, 0)])  # ~1 acre


def _listing(listing_id="l1", **overrides):
    defaults = dict(
        id=listing_id, formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.20, longitude=-77.90, status="Active",
        price=600000, square_footage=2000, year_built=1985, lot_size_sqft=20000,
        raw={"bedrooms": 3, "bathrooms": 2.5, "daysOnMarket": 14, "hoa": {"fee": 50},
             "history": {"2026-01-01": {"price": 620000}, "2026-02-01": {"price": 600000}}},
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _patch_gis(monkeypatch, *, boundary=None, wetland_pct=0.1, rear_open=45.0, neighborhood_canopy=55.0):
    monkeypatch.setattr(
        "canopy.features.nhc_gis.compute_boundary_features",
        lambda poly: boundary or {
            "protected_perimeter_ratio": 0.4, "abuts_water": True, "abuts_marsh_wetland": False,
            "abuts_park_public": True, "abuts_conservation_easement": False, "abuts_buildable_private": True,
            "edges": {"n": "water", "e": "buildable", "s": "park", "w": "buildable"},
        },
    )
    monkeypatch.setattr("canopy.features.nhc_gis.wetland_pct_of_parcel", lambda poly: wetland_pct)
    monkeypatch.setattr("canopy.features.nhc_gis.rear_open_distance_ft", lambda poly, pid: rear_open)
    monkeypatch.setattr(
        "canopy.features.canopy_raster.neighborhood_canopy_buffer_pct",
        lambda geom, crs, buffer_m: neighborhood_canopy,
    )


def test_market_fields_parses_days_hoa_and_price_cuts():
    listing = _listing()

    result = _market_fields(listing)

    assert result["days_on_market"] == 14
    assert result["hoa_fee_monthly"] == 50
    assert result["price_cut_count"] == 1  # 620000 -> 600000


def test_market_fields_no_price_cut_when_price_rises_or_holds():
    listing = _listing(raw={
        "history": {"2026-01-01": {"price": 500000}, "2026-02-01": {"price": 520000}},
    })

    assert _market_fields(listing)["price_cut_count"] == 0


def test_market_fields_missing_hoa_and_days_on_market():
    listing = _listing(raw={}, listed_date=None)

    result = _market_fields(listing)

    assert result["hoa_fee_monthly"] is None
    assert result["days_on_market"] is None


def test_market_fields_falls_back_to_listed_date_for_days_on_market():
    ten_days_ago = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(days=10)
    listing = _listing(raw={}, listed_date=ten_days_ago)

    assert _market_fields(listing)["days_on_market"] == 10


def test_haversine_ft_zero_for_same_point():
    assert _haversine_ft(34.2, -77.9, 34.2, -77.9) == 0


def test_median_year_built_buffer_uses_nearby_listings_only(session):
    subject = _listing("subject", latitude=34.20, longitude=-77.90, year_built=None)
    near1 = _listing("near1", latitude=34.2005, longitude=-77.90, year_built=1960)
    near2 = _listing("near2", latitude=34.1995, longitude=-77.90, year_built=1980)
    far = _listing("far", latitude=35.0, longitude=-77.0, year_built=2020)  # way outside radius
    session.add_all([subject, near1, near2, far])
    session.commit()

    result = _median_year_built_buffer(session, subject, radius_ft=500)

    assert result == 1970  # median of 1960 and 1980


def test_median_year_built_buffer_none_when_no_neighbors(session):
    subject = _listing("subject")
    session.add(subject)
    session.commit()

    assert _median_year_built_buffer(session, subject, radius_ft=500) is None


def test_compute_feature_vector_full_data(session, monkeypatch):
    _patch_gis(monkeypatch)
    listing = _listing()
    parcel = Parcel(listing_id="l1", parcel_id="R001", geometry_geojson=mapping(SQUARE_PARCEL))
    score = Score(listing_id="l1", canopy_pct=42.0)
    session.add_all([listing, parcel, score])
    session.commit()

    vector = compute_feature_vector(session, listing, parcel, score)

    assert vector["lot_acreage"] is not None
    assert vector["protected_perimeter_ratio"] == 0.4
    assert vector["abuts_water"] is True
    assert vector["parcel_canopy_pct"] == 42.0
    assert vector["neighborhood_canopy_pct"] == 55.0
    assert vector["canopy_delta"] == 55.0 - 42.0
    assert vector["price_per_sqft"] == 300.0
    assert vector["beds"] == 3
    assert "stories" in vector["imputed_fields"]  # RentCast never provides this
    assert "lot_acreage" not in vector["imputed_fields"]
    assert vector["extra"]["edges"] == {"n": "water", "e": "buildable", "s": "park", "w": "buildable"}
    # SQUARE_PARCEL has real geometry, so a simplified outline should be
    # computed and attached even though _patch_gis doesn't mock it
    assert len(vector["extra"]["parcel_outline"]) == 4


def test_compute_feature_vector_fronting_road_class_from_dominant_road_side(session, monkeypatch):
    _patch_gis(monkeypatch, boundary={
        "protected_perimeter_ratio": 0.0, "abuts_water": False, "abuts_marsh_wetland": False,
        "abuts_park_public": False, "abuts_conservation_easement": False, "abuts_buildable_private": False,
        "edges": {"n": "buildable", "e": "road", "s": "road", "w": "buildable"},
        "road_edges": {
            "s": {"touch_len_ft": 30.0, "path": [[-50, -50], [50, -50]], "road_class": "residential", "street_name": "Parkwood Dr"},
            "e": {"touch_len_ft": 90.0, "path": [[50, -50], [50, 50]], "road_class": "primary", "street_name": "Oleander Ave"},
        },
    })
    listing = _listing()
    parcel = Parcel(listing_id="l1", parcel_id="R001", geometry_geojson=mapping(SQUARE_PARCEL))
    score = Score(listing_id="l1", canopy_pct=42.0)
    session.add_all([listing, parcel, score])
    session.commit()

    vector = compute_feature_vector(session, listing, parcel, score)

    # the east side has the longer real road touch (90ft vs 30ft), so its
    # classification wins the scalar fronting_road_class
    assert vector["fronting_road_class"] == "primary"
    assert vector["extra"]["road_edges"]["e"]["street_name"] == "Oleander Ave"
    assert "fronting_road_class" not in vector["imputed_fields"]


def test_compute_feature_vector_fronting_road_class_imputed_when_no_road_side(session, monkeypatch):
    _patch_gis(monkeypatch)  # default boundary has no "road" edges
    listing = _listing()
    parcel = Parcel(listing_id="l1", parcel_id="R001", geometry_geojson=mapping(SQUARE_PARCEL))
    score = Score(listing_id="l1", canopy_pct=42.0)
    session.add_all([listing, parcel, score])
    session.commit()

    vector = compute_feature_vector(session, listing, parcel, score)

    assert vector["fronting_road_class"] is None
    assert "fronting_road_class" in vector["imputed_fields"]


def test_compute_feature_vector_no_parcel_imputes_geometry_fields(session, monkeypatch):
    _patch_gis(monkeypatch)
    listing = _listing()
    session.add(listing)
    session.commit()

    vector = compute_feature_vector(session, listing, None, None)

    assert vector["protected_perimeter_ratio"] is None
    assert "protected_perimeter_ratio" in vector["imputed_fields"]
    assert "abuts_water" in vector["imputed_fields"]
    # falls back to RentCast-reported lot size, not fully imputed
    assert vector["lot_acreage"] == 20000 / 43560
    assert "lot_acreage" not in vector["imputed_fields"]


def test_compute_features_for_listings_persists_and_is_idempotent(session, monkeypatch):
    _patch_gis(monkeypatch)
    listing = _listing()
    parcel = Parcel(listing_id="l1", parcel_id="R001", geometry_geojson=mapping(SQUARE_PARCEL))
    score = Score(listing_id="l1", canopy_pct=42.0)
    session.add_all([listing, parcel, score])
    session.commit()

    first = compute_features_for_listings(session, [listing])
    assert len(first) == 1
    assert session.query(ListingFeatures).count() == 1

    # re-running for the same listing should update the existing row, not
    # insert a duplicate (same listing_id + feature_set_version PK)
    second = compute_features_for_listings(session, [listing])
    assert len(second) == 1
    assert session.query(ListingFeatures).count() == 1
    assert second[0].feature_set_version == FEATURE_SET_VERSION


def test_compute_feature_vector_avg_room_sqft(session, monkeypatch):
    _patch_gis(monkeypatch)
    listing = _listing(square_footage=2400, raw={"bedrooms": 4, "bathrooms": 2})
    session.add(listing)
    session.commit()

    vector = compute_feature_vector(session, listing, None, None)

    assert vector["avg_room_sqft"] == 600.0
    assert "avg_room_sqft" not in vector["imputed_fields"]


def test_compute_feature_vector_avg_room_sqft_imputed_when_beds_missing(session, monkeypatch):
    _patch_gis(monkeypatch)
    listing = _listing(square_footage=2400, raw={"bathrooms": 2})
    session.add(listing)
    session.commit()

    vector = compute_feature_vector(session, listing, None, None)

    assert vector["avg_room_sqft"] is None
    assert "avg_room_sqft" in vector["imputed_fields"]


def test_is_tract_new_build_true_when_recent_and_clustered(session, monkeypatch):
    """Many nearby listings sharing the same recent year_built is the
    tract/subdivision signature -- the case the user wants flagged
    (not excluded)."""
    _patch_gis(monkeypatch)
    current_year = dt.date.today().year
    subject = _listing("subject", year_built=current_year - 1)
    neighbor1 = _listing("n1", latitude=34.2005, longitude=-77.90, year_built=current_year - 2)
    neighbor2 = _listing("n2", latitude=34.1995, longitude=-77.90, year_built=current_year - 2)
    session.add_all([subject, neighbor1, neighbor2])
    session.commit()

    vector = compute_feature_vector(session, subject, None, None)

    assert vector["is_tract_new_build"] is True


def test_is_tract_new_build_false_for_new_custom_infill(session, monkeypatch):
    """A recently built house surrounded by much older neighbors is a
    custom infill, not a tract build -- exactly the "good lot" case the
    user doesn't want silently lost. median_year_built_buffer being far
    from year_built should keep this False despite the recent build."""
    _patch_gis(monkeypatch)
    current_year = dt.date.today().year
    subject = _listing("subject", year_built=current_year - 1)
    neighbor1 = _listing("n1", latitude=34.2005, longitude=-77.90, year_built=1965)
    neighbor2 = _listing("n2", latitude=34.1995, longitude=-77.90, year_built=1970)
    session.add_all([subject, neighbor1, neighbor2])
    session.commit()

    vector = compute_feature_vector(session, subject, None, None)

    assert vector["is_tract_new_build"] is False


def test_is_tract_new_build_false_when_not_recent(session, monkeypatch):
    _patch_gis(monkeypatch)
    subject = _listing("subject", year_built=1985)
    neighbor = _listing("n1", latitude=34.2005, longitude=-77.90, year_built=1985)
    session.add_all([subject, neighbor])
    session.commit()

    vector = compute_feature_vector(session, subject, None, None)

    assert vector["is_tract_new_build"] is False
    assert "is_tract_new_build" not in vector["imputed_fields"]


def test_is_tract_new_build_imputed_when_no_neighbors(session, monkeypatch):
    _patch_gis(monkeypatch)
    current_year = dt.date.today().year
    subject = _listing("subject", year_built=current_year - 1)
    session.add(subject)
    session.commit()

    vector = compute_feature_vector(session, subject, None, None)

    assert vector["is_tract_new_build"] is None
    assert "is_tract_new_build" in vector["imputed_fields"]


def test_anchor_rollups_min_and_mean_by_category(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(_listing())
    beach = Anchor(label="Beach A", category="beach", lat=34.2, lon=-77.8, created_by="zach")
    friend1 = Anchor(label="Friend 1", category="social", lat=34.2, lon=-77.8, created_by="zach")
    friend2 = Anchor(label="Friend 2", category="social", lat=34.2, lon=-77.8, created_by="zach")
    session.add_all([beach, friend1, friend2])
    session.commit()

    session.add_all([
        ListingAnchorTime(listing_id="l1", anchor_id=beach.id, drive_minutes=20.0, is_proxy=True),
        ListingAnchorTime(listing_id="l1", anchor_id=friend1.id, drive_minutes=10.0, is_proxy=True),
        ListingAnchorTime(listing_id="l1", anchor_id=friend2.id, drive_minutes=30.0, is_proxy=True),
    ])
    session.commit()

    result = anchor_rollups(session, "l1")

    assert result["min_drive_beach"] == 20.0
    assert result["mean_drive_social"] == 20.0  # (10 + 30) / 2
    assert result["min_drive_grocery"] is None  # no grocery anchors at all


def test_anchor_rollups_ignores_inactive_anchors(session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.add(_listing())
    anchor = Anchor(label="Old Beach", category="beach", lat=34.2, lon=-77.8, created_by="zach", active=False)
    session.add(anchor)
    session.commit()
    session.add(ListingAnchorTime(listing_id="l1", anchor_id=anchor.id, drive_minutes=20.0, is_proxy=True))
    session.commit()

    result = anchor_rollups(session, "l1")

    assert result["min_drive_beach"] is None
