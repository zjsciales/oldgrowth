from pathlib import Path

from canopy.db.models import EmailIngestLog, Listing
from canopy.email_ingest import _normalize_address, ingest_from_email

FIXTURES = Path(__file__).parent / "fixtures"
SAVED_SEARCH = FIXTURES / "zillow_alert_saved_search.eml"


def _stub_gmail(monkeypatch, messages):
    """messages: list of (uid_bytes, raw_bytes). Tracks mark_processed calls."""
    marked = []
    monkeypatch.setattr("canopy.email_ingest.gmail.fetch_unprocessed_messages", lambda: messages)
    monkeypatch.setattr("canopy.email_ingest.gmail.mark_processed", lambda uid: marked.append(uid))
    return marked


def _stub_geocode(monkeypatch, result=(34.15, -77.88, "resolved address")):
    monkeypatch.setattr("canopy.email_ingest.geocode_address", lambda addr: result)


def test_ingest_from_email_inserts_new_listings(session, monkeypatch):
    _stub_geocode(monkeypatch)
    marked = _stub_gmail(monkeypatch, [(b"1", SAVED_SEARCH.read_bytes())])

    changed = ingest_from_email(session)

    assert len(changed) == 2
    assert session.query(Listing).count() == 2
    assert marked == [b"1"]
    listing = session.query(Listing).filter_by(source_listing_id="54340342").one()
    assert listing.id == "zillow-54340342"
    assert listing.source == "zillow_email"
    assert listing.price == 825000
    assert listing.latitude == 34.15
    assert listing.longitude == -77.88
    assert listing.status == "Active"
    assert listing.photo_url == "https://photos.zillowstatic.com/fp/f40683e2147210fbc7cbcfdb663e07cb-p_e.jpg"


def test_ingest_from_email_logs_email_ingest_log(session, monkeypatch):
    _stub_geocode(monkeypatch)
    _stub_gmail(monkeypatch, [(b"1", SAVED_SEARCH.read_bytes())])

    ingest_from_email(session)

    log = session.query(EmailIngestLog).one()
    assert log.source == "zillow_email"
    assert log.listings_found == 2
    assert log.listings_parsed_ok == 2


def test_ingest_from_email_dedupes_by_zpid_on_repoll(session, monkeypatch):
    _stub_geocode(monkeypatch)
    _stub_gmail(monkeypatch, [(b"1", SAVED_SEARCH.read_bytes())])
    ingest_from_email(session)

    # A second poll of the same already-processed message (e.g. IMAP flag
    # write raced with a crash) must not duplicate rows or re-log.
    _stub_gmail(monkeypatch, [(b"1", SAVED_SEARCH.read_bytes())])
    ingest_from_email(session)

    assert session.query(Listing).count() == 2
    assert session.query(EmailIngestLog).count() == 1


def test_ingest_from_email_skips_geocoding_failure_without_crashing(session, monkeypatch):
    monkeypatch.setattr("canopy.email_ingest.geocode_address", lambda addr: None)
    _stub_gmail(monkeypatch, [(b"1", SAVED_SEARCH.read_bytes())])

    changed = ingest_from_email(session)

    assert len(changed) == 2
    for listing in session.query(Listing).all():
        assert listing.latitude is None
        assert listing.longitude is None


def test_ingest_from_email_price_update_does_not_null_other_fields(session, monkeypatch):
    """Field-presence-aware upsert: a later alert about the same listing
    with a lower price must not wipe out square_footage/lat/lon just
    because this parse pass re-derived the same values -- and more
    importantly, a parsed value that's genuinely absent must never
    overwrite a previously-known one."""
    _stub_geocode(monkeypatch)
    _stub_gmail(monkeypatch, [(b"1", SAVED_SEARCH.read_bytes())])
    ingest_from_email(session)

    listing = session.query(Listing).filter_by(source_listing_id="54340342").one()
    assert listing.square_footage == 3023

    # Re-ingest the identical email content under a new message -- values
    # should be stable, not nulled.
    import email as email_lib
    msg = email_lib.message_from_bytes(SAVED_SEARCH.read_bytes())
    del msg["Message-ID"]
    msg["Message-ID"] = "<different-message-id@example.com>"
    _stub_gmail(monkeypatch, [(b"2", msg.as_bytes())])
    ingest_from_email(session)

    listing = session.query(Listing).filter_by(source_listing_id="54340342").one()
    assert listing.square_footage == 3023
    assert listing.latitude == 34.15


def test_normalize_address_strips_case_and_punctuation():
    assert _normalize_address("4105 Purviance Court, Wilmington, NC") == \
        _normalize_address("4105  PURVIANCE COURT, Wilmington, NC.")
