import datetime as dt

from canopy.cli import _unenriched_backlog, _unfeatured_backlog, run_weekly
from canopy.db.models import Listing, ListingFeatures, Parcel, Rater


def _listing(listing_id: str) -> Listing:
    return Listing(
        id=listing_id, formatted_address=f"{listing_id} Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9,
        status="Active", price=500000, raw={},
    )


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


class _FakeModelRun:
    def __init__(self, rater_id):
        self.rater_id = rater_id
        self.id = 1
        self.n_pairs = 0
        self.holdout_accuracy = None


def _stub_downstream_of_features(monkeypatch, session):
    """Stubs everything from Stage 5 onward so run_weekly tests can focus
    on Stage 1-4 backlog behavior without needing real model fitting."""
    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.cli.fit_model", lambda s, rater_id: _FakeModelRun(rater_id))
    monkeypatch.setattr("canopy.cli.score_preferences", lambda s, model_run: [])
    monkeypatch.setattr("canopy.cli.compute_digest_slots", lambda s, a, b: {"ready": False})
    monkeypatch.setattr("canopy.cli.send_digest", lambda s, plan, dry_run=False: "")


# ---------------------------------------------------------------------------
# _unenriched_backlog
# ---------------------------------------------------------------------------


def test_unenriched_backlog_includes_listings_with_no_parcel(session):
    session.add(_listing("l1"))
    session.commit()

    assert [listing.id for listing in _unenriched_backlog(session)] == ["l1"]


def test_unenriched_backlog_excludes_enriched_listings(session):
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=_now()))
    session.commit()

    assert _unenriched_backlog(session) == []


def test_unenriched_backlog_includes_listings_enriched_but_not_finished(session):
    # Parcel row exists but enriched_at is still null -- e.g. a crash
    # between creating the row and setting the timestamp.
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=None))
    session.commit()

    assert [listing.id for listing in _unenriched_backlog(session)] == ["l1"]


# ---------------------------------------------------------------------------
# _unfeatured_backlog
# ---------------------------------------------------------------------------


def test_unfeatured_backlog_includes_listings_with_no_features(session):
    session.add(_listing("l1"))
    session.commit()

    assert [listing.id for listing in _unfeatured_backlog(session)] == ["l1"]


def test_unfeatured_backlog_excludes_featured_listings(session):
    session.add(_listing("l1"))
    session.add(ListingFeatures(listing_id="l1", feature_set_version="v1"))
    session.commit()

    assert _unfeatured_backlog(session) == []


def test_unfeatured_backlog_ignores_stale_feature_set_versions(session):
    # a row exists, but for an old feature_set_version -- still counts as
    # needing (re)computation under the current one
    session.add(_listing("l1"))
    session.add(ListingFeatures(listing_id="l1", feature_set_version="v0-stale"))
    session.commit()

    assert [listing.id for listing in _unfeatured_backlog(session)] == ["l1"]


# ---------------------------------------------------------------------------
# run_weekly
# ---------------------------------------------------------------------------


def test_run_weekly_reprocesses_stuck_enrichment_backlog(monkeypatch, session):
    """Simulates a prior crash: l1 was ingested and enriched, l2 was
    ingested but never enriched. This run's ingest finds nothing new
    (changed=[]) -- l2 must still get carried through enrichment/scoring."""
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=_now()))
    session.add(_listing("l2"))
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [])
    enrich_calls, score_canopy_calls = [], []
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: enrich_calls.extend(x.id for x in listings))
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: score_canopy_calls.extend(x.id for x in listings))
    monkeypatch.setattr("canopy.cli.compute_features_for_listings", lambda s, listings: None)
    _stub_downstream_of_features(monkeypatch, session)

    run_weekly()

    assert enrich_calls == ["l2"]
    assert score_canopy_calls == ["l2"]


def test_run_weekly_reprocesses_stuck_feature_backlog(monkeypatch, session):
    """l1 was enriched+featured already; l2 was enriched but never got a
    feature vector (e.g. a crash mid-Stage-4)."""
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=_now()))
    session.add(ListingFeatures(listing_id="l1", feature_set_version="v1"))
    session.add(_listing("l2"))
    session.add(Parcel(listing_id="l2", enriched_at=_now()))
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [])
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: None)
    feature_calls = []
    monkeypatch.setattr(
        "canopy.cli.compute_features_for_listings", lambda s, listings: feature_calls.extend(x.id for x in listings)
    )
    _stub_downstream_of_features(monkeypatch, session)

    run_weekly()

    assert feature_calls == ["l2"]


def test_run_weekly_refits_both_raters_in_id_order_and_sends_digest(monkeypatch, session):
    session.add(_listing("l1"))
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [session.get(Listing, "l1")])
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.compute_features_for_listings", lambda s, listings: None)

    fit_calls = []
    monkeypatch.setattr(
        "canopy.cli.fit_model",
        lambda s, rater_id: fit_calls.append(rater_id) or _FakeModelRun(rater_id),
    )
    score_pref_calls = []
    monkeypatch.setattr(
        "canopy.cli.score_preferences", lambda s, model_run: score_pref_calls.append(model_run.rater_id)
    )
    digest_calls = []
    monkeypatch.setattr(
        "canopy.cli.compute_digest_slots",
        lambda s, a, b: digest_calls.append((a, b)) or {"ready": False},
    )
    send_calls = []
    monkeypatch.setattr("canopy.cli.send_digest", lambda s, plan, dry_run=False: send_calls.append(plan) or "")

    run_weekly()

    # Rater.id-ordered: "andrea" sorts before "zach"
    assert fit_calls == ["andrea", "zach"]
    assert score_pref_calls == ["andrea", "zach"]
    assert digest_calls == [("andrea", "zach")]
    assert len(send_calls) == 1


def test_run_weekly_skips_model_refit_without_exactly_two_raters(monkeypatch, session):
    session.add(_listing("l1"))
    session.add(Rater(id="zach", display_name="Zach"))  # only one rater
    session.commit()

    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [session.get(Listing, "l1")])
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.compute_features_for_listings", lambda s, listings: None)
    fit_calls = []
    monkeypatch.setattr("canopy.cli.fit_model", lambda s, rater_id: fit_calls.append(rater_id))

    run_weekly()

    assert fit_calls == []


def test_run_weekly_exits_early_when_nothing_new_and_no_backlog(monkeypatch, session):
    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [])
    fit_calls = []
    monkeypatch.setattr("canopy.cli.fit_model", lambda s, rater_id: fit_calls.append(rater_id))

    run_weekly()

    assert fit_calls == []
