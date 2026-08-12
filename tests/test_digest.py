from canopy.db.models import DigestLog, Listing, ListingFeatures, Parcel, Score
from canopy.digest import render_digest_html, send_digest


def _make_listing(session, listing_id="l1"):
    listing = Listing(
        id=listing_id, formatted_address="1 Test St", city="Wilmington", state="NC",
        zip_code="28409", latitude=34.1, longitude=-77.9, status="Active",
        year_built=1970, lot_size_sqft=20000, price=800000, raw={},
    )
    parcel = Parcel(listing_id=listing_id, parcel_id="R12345", adjacent_water=True)
    features = ListingFeatures(listing_id=listing_id, feature_set_version="v1", parcel_canopy_pct=65.0)
    score = Score(listing_id=listing_id, canopy_pct=65.0, subagent_rationale="Backs to marsh.")
    session.add_all([listing, parcel, features, score])
    session.commit()
    return listing


def _detail(listing_id, joint_score=1.0):
    return {
        "listing_id": listing_id, "joint_score": joint_score, "agreement_score": joint_score,
        "disagreement": 0.0, "z_a": joint_score, "z_b": joint_score,
    }


def _empty_plan(**overrides):
    plan = {"ready": True, "top_ranked": [], "uncertain": [], "wildcard": [], "disagreements": []}
    plan.update(overrides)
    return plan


def test_render_digest_html_not_ready():
    html = render_digest_html(None, {"ready": False})
    assert "Still calibrating" in html


def test_render_digest_html_with_top_ranked(session):
    _make_listing(session)

    html = render_digest_html(session, _empty_plan(top_ranked=[_detail("l1")]))

    assert "1 Test St" in html
    assert "Backs to marsh" in html
    assert "R12345" in html
    assert "$800,000" in html
    assert "Top ranked" in html


def test_render_digest_html_shows_disagreement_section(session):
    _make_listing(session)

    html = render_digest_html(session, _empty_plan(disagreements=[_detail("l1")]))

    assert "You two disagree about these" in html
    assert "1 Test St" in html


def test_render_digest_html_hides_disagreement_section_when_empty(session):
    _make_listing(session)

    html = render_digest_html(session, _empty_plan(top_ranked=[_detail("l1")]))

    assert "You two disagree" not in html


def test_send_digest_dry_run_does_not_send_or_log(session, monkeypatch):
    _make_listing(session)
    plan = _empty_plan(top_ranked=[_detail("l1")])

    def fail_smtp(*args, **kwargs):
        raise AssertionError("SMTP should not be called in dry-run")

    monkeypatch.setattr("smtplib.SMTP", fail_smtp)

    html = send_digest(session, plan, dry_run=True)

    assert "1 Test St" in html
    assert session.query(DigestLog).count() == 0


class _FakeSMTP:
    def __init__(self, host, port):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, msg):
        _FakeSMTP.sent = (from_addr, to_addrs)


def test_send_digest_sends_and_logs(session, monkeypatch):
    _make_listing(session)
    plan = _empty_plan(top_ranked=[_detail("l1")])

    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    monkeypatch.setattr("canopy.digest.SMTP_USER", "test@example.com")
    monkeypatch.setattr("canopy.digest.SMTP_PASS", "app-password")
    monkeypatch.setattr("canopy.digest.DIGEST_TO_EMAIL", "me@example.com")

    send_digest(session, plan)

    assert _FakeSMTP.sent == ("test@example.com", ["me@example.com"])
    assert session.query(DigestLog).count() == 1


def test_send_digest_not_ready_still_sends_a_calibrating_message(session, monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", _FakeSMTP)
    monkeypatch.setattr("canopy.digest.SMTP_USER", "test@example.com")
    monkeypatch.setattr("canopy.digest.SMTP_PASS", "app-password")
    monkeypatch.setattr("canopy.digest.DIGEST_TO_EMAIL", "me@example.com")

    html = send_digest(session, {"ready": False})

    assert _FakeSMTP.sent == ("test@example.com", ["me@example.com"])
    assert "Still calibrating" in html
    assert session.query(DigestLog).count() == 0
