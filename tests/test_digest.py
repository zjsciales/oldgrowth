from canopy.db.models import Listing, Parcel, Score
from canopy.digest import render_digest_html, send_digest


def _make_listing(session, listing_id="l1"):
    listing = Listing(
        id=listing_id, formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=1970, lot_size_sqft=20000, price=800000, raw={},
    )
    parcel = Parcel(listing_id=listing_id, parcel_id="R12345", adjacent_water=True)
    score = Score(listing_id=listing_id, canopy_pct=65.0, subagent_rationale="Backs to marsh.")
    session.add_all([listing, parcel, score])
    session.commit()
    return listing


def test_render_digest_html_empty():
    html = render_digest_html([])
    assert "No new candidates" in html


def test_render_digest_html_with_candidate(session):
    listing = _make_listing(session)
    parcel = session.query(Parcel).filter_by(listing_id="l1").one()
    score = session.query(Score).filter_by(listing_id="l1").one()

    html = render_digest_html([(listing, parcel, score)])

    assert "1 Test St" in html
    assert "Backs to marsh" in html
    assert "R12345" in html
    assert "$800,000" in html


def test_send_digest_dry_run_does_not_send_or_log(session, monkeypatch):
    listing = _make_listing(session)

    def fail_smtp(*args, **kwargs):
        raise AssertionError("SMTP should not be called in dry-run")

    monkeypatch.setattr("smtplib.SMTP", fail_smtp)

    html = send_digest(session, [listing], dry_run=True)

    assert "1 Test St" in html
    from canopy.db.models import DigestLog
    assert session.query(DigestLog).count() == 0


def test_send_digest_sends_and_logs(session, monkeypatch):
    listing = _make_listing(session)
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def starttls(self):
            sent["starttls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def sendmail(self, from_addr, to_addrs, msg):
            sent["sendmail"] = (from_addr, to_addrs)

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("canopy.digest.SMTP_USER", "test@example.com")
    monkeypatch.setattr("canopy.digest.SMTP_PASS", "app-password")
    monkeypatch.setattr("canopy.digest.DIGEST_TO_EMAIL", "me@example.com")

    send_digest(session, [listing])

    assert sent["sendmail"] == ("test@example.com", ["me@example.com"])
    from canopy.db.models import DigestLog
    assert session.query(DigestLog).count() == 1
