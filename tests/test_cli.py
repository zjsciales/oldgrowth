import datetime as dt

from canopy.cli import _unenriched_backlog, run_weekly
from canopy.db.models import Listing, Parcel, Score


def _listing(listing_id: str) -> Listing:
    return Listing(
        id=listing_id, formatted_address=f"{listing_id} Test St", city="Wilmington",
        state="NC", zip_code="28409", latitude=34.1, longitude=-77.9,
        status="Active", price=500000, raw={},
    )


def test_unenriched_backlog_includes_listings_with_no_parcel(session):
    session.add(_listing("l1"))
    session.commit()

    backlog = _unenriched_backlog(session)

    assert [listing.id for listing in backlog] == ["l1"]


def test_unenriched_backlog_excludes_enriched_listings(session):
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)))
    session.commit()

    assert _unenriched_backlog(session) == []


def test_unenriched_backlog_includes_listings_enriched_but_not_finished(session):
    # Parcel row exists but enriched_at is still null -- e.g. a crash
    # between creating the row and setting the timestamp.
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=None))
    session.commit()

    backlog = _unenriched_backlog(session)

    assert [listing.id for listing in backlog] == ["l1"]


def test_run_weekly_reprocesses_stuck_backlog_without_new_rentcast_data(monkeypatch, session):
    """Simulates a prior crash: l1 was ingested and enriched, l2 was
    ingested but never enriched. This run's ingest finds nothing new
    (changed=[]) -- l2 must still get carried through the pipeline."""
    session.add(_listing("l1"))
    session.add(Parcel(listing_id="l1", enriched_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)))
    session.add(_listing("l2"))
    session.commit()

    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [])

    enriched_ids = []
    monkeypatch.setattr(
        "canopy.cli.enrich_listings", lambda s, listings: enriched_ids.extend(x.id for x in listings)
    )
    scored_ids = []
    monkeypatch.setattr(
        "canopy.cli.score_listings", lambda s, listings: scored_ids.extend(x.id for x in listings)
    )
    monkeypatch.setattr("canopy.cli.filter_listings", lambda s, listings: [])

    run_weekly()

    assert enriched_ids == ["l2"]
    assert scored_ids == ["l2"]


def test_run_weekly_skips_already_evaluated_candidates_in_subagent_stage(monkeypatch, session):
    listing_evaluated = _listing("l1")
    listing_new = _listing("l2")
    session.add_all([listing_evaluated, listing_new])
    session.add(Parcel(listing_id="l1", enriched_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)))
    session.add(Parcel(listing_id="l2", enriched_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)))
    session.add(Score(listing_id="l1", subagent_rationale="Already reviewed."))
    session.add(Score(listing_id="l2"))
    session.commit()

    monkeypatch.setattr("canopy.cli.SessionLocal", lambda: session)
    monkeypatch.setattr("canopy.cli.ingest_all_zips", lambda s: [listing_evaluated, listing_new])
    monkeypatch.setattr("canopy.cli.enrich_listings", lambda s, listings: None)
    monkeypatch.setattr("canopy.cli.score_listings", lambda s, listings: None)
    monkeypatch.setattr(
        "canopy.cli.filter_listings", lambda s, listings: [listing_evaluated, listing_new]
    )

    subagent_calls = []
    monkeypatch.setattr(
        "canopy.cli.run_subagent_on_candidates", lambda s, candidates: subagent_calls.extend(candidates)
    )
    monkeypatch.setattr("canopy.cli.send_digest", lambda s, candidates, dry_run=False: "")

    run_weekly()

    assert [c.id for c in subagent_calls] == ["l2"]
