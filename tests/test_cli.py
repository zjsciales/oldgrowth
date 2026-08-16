import datetime as dt

from canopy.cli import _unenriched_backlog, _unfeatured_backlog, run_daily, run_digest, run_pipeline
from canopy.db.models import Listing, ListingFeatures, Parcel, Rater


def _listing(listing_id: str, property_type: str | None = None, formatted_address: str | None = None) -> Listing:
    return Listing(
        id=listing_id, formatted_address=formatted_address or f"{listing_id} Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9,
        status="Active", price=500000, raw={}, property_type=property_type,
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
    """Stubs everything from Stage 5 onward so run_pipeline tests can focus
    on Stage 1-4 backlog behavior without needing real model fitting."""
    monkeypatch.setattr("canopy.cli.fit_model", lambda s, rater_id: _FakeModelRun(rater_id))
    monkeypatch.setattr("canopy.cli.score_preferences", lambda s, model_run: [])


# ---------------------------------------------------------------------------
# _unenriched_backlog / _unfeatured_backlog (unchanged behavior)
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


def test_unfeatured_backlog_includes_listings_with_no_features(session):
    session.add(_listing("l1"))
    session.commit()

    assert [listing.id for listing in _unfeatured_backlog(session)] == ["l1"]


def test_unfeatured_backlog_excludes_featured_listings(session):
    session.add(_listing("l1"))
    session.add(ListingFeatures(listing_id="l1", feature_set_version="v1"))
    session.commit()

    assert _unfeatured_backlog(session) == []


# ---------------------------------------------------------------------------
# run_pipeline (Stages 1-5, ingest_fn is swappable)
# ---------------------------------------------------------------------------


def test_run_pipeline_reprocesses_stuck_enrichment_backlog(monkeypatch, session):
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=_now()))
    session.add(_listing("l2"))
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    enrich_calls, score_canopy_calls = [], []
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: enrich_calls.extend(x.id for x in listings))
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: score_canopy_calls.extend(x.id for x in listings))
    monkeypatch.setattr("canopy.cli.compute_features_for_listings", lambda s, listings: None)
    _stub_downstream_of_features(monkeypatch, session)

    ran = run_pipeline(session, ingest_fn=lambda s: [])

    assert ran is True
    assert enrich_calls == ["l2"]
    assert score_canopy_calls == ["l2"]


def test_run_pipeline_skips_excluded_property_types(monkeypatch, session):
    session.add(_listing("l1", property_type="Single Family"))
    session.add(_listing("l2", property_type="Condo"))
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    enrich_calls, feature_calls = [], []
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: enrich_calls.extend(x.id for x in listings))
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: None)
    monkeypatch.setattr(
        "canopy.cli.compute_features_for_listings", lambda s, listings: feature_calls.extend(x.id for x in listings)
    )
    _stub_downstream_of_features(monkeypatch, session)

    def ingest_fn(s):
        return [session.get(Listing, "l1"), session.get(Listing, "l2")]

    run_pipeline(session, ingest_fn=ingest_fn)

    assert enrich_calls == ["l1"]
    assert feature_calls == ["l1"]


def test_run_pipeline_refits_both_raters_in_id_order(monkeypatch, session):
    session.add(_listing("l1"))
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.compute_features_for_listings", lambda s, listings: None)

    fit_calls = []
    monkeypatch.setattr(
        "canopy.cli.fit_model", lambda s, rater_id: fit_calls.append(rater_id) or _FakeModelRun(rater_id)
    )
    score_pref_calls = []
    monkeypatch.setattr(
        "canopy.cli.score_preferences", lambda s, model_run: score_pref_calls.append(model_run.rater_id)
    )

    def ingest_fn(s):
        return [session.get(Listing, "l1")]

    run_pipeline(session, ingest_fn=ingest_fn)

    assert fit_calls == ["andrea", "zach"]
    assert score_pref_calls == ["andrea", "zach"]


def test_run_pipeline_skips_model_refit_without_exactly_two_raters(monkeypatch, session):
    session.add(_listing("l1"))
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.score_canopy", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.compute_features_for_listings", lambda s, listings: None)
    fit_calls = []
    monkeypatch.setattr("canopy.cli.fit_model", lambda s, rater_id: fit_calls.append(rater_id))

    def ingest_fn(s):
        return [session.get(Listing, "l1")]

    ran = run_pipeline(session, ingest_fn=ingest_fn)

    assert ran is True  # Stages 1-4 still ran; only the refit was skipped
    assert fit_calls == []


def test_run_pipeline_returns_false_when_nothing_new_and_no_backlog(session):
    ran = run_pipeline(session, ingest_fn=lambda s: [])

    assert ran is False


def test_run_daily_uses_email_ingest(monkeypatch, session):
    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    calls = []
    monkeypatch.setattr("canopy.cli.ingest_from_email", lambda s: calls.append("called") or [])

    run_daily()

    assert calls == ["called"]


# ---------------------------------------------------------------------------
# run_digest (Stage 6 only, independent schedule)
# ---------------------------------------------------------------------------


def test_run_digest_sends_using_latest_state(monkeypatch, session):
    session.add_all([Rater(id="zach", display_name="Zach"), Rater(id="andrea", display_name="Andrea")])
    session.commit()

    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    digest_calls = []
    monkeypatch.setattr(
        "canopy.cli.compute_digest_slots", lambda s, a, b: digest_calls.append((a, b)) or {"ready": False}
    )
    send_calls = []
    monkeypatch.setattr("canopy.cli.send_digest", lambda s, plan, dry_run=False: send_calls.append(plan) or "")

    run_digest()

    assert digest_calls == [("andrea", "zach")]
    assert len(send_calls) == 1


def test_run_digest_skips_without_exactly_two_raters(monkeypatch, session):
    session.add(Rater(id="zach", display_name="Zach"))
    session.commit()

    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    digest_calls = []
    monkeypatch.setattr("canopy.cli.compute_digest_slots", lambda s, a, b: digest_calls.append((a, b)))

    run_digest()

    assert digest_calls == []
