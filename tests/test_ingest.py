import json
from pathlib import Path

from canopy.db.models import Listing
from canopy.ingest import ingest_all_zips

FIXTURE = Path(__file__).parent / "fixtures" / "rentcast_sale_listings_28409.json"


def test_ingest_all_zips_inserts_new_listings(session, monkeypatch):
    data = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(
        "canopy.ingest.fetch_sale_listings_for_zip", lambda zip_code: data
    )

    changed = ingest_all_zips(session, zips=["28409"])

    assert len(changed) == 2
    assert session.query(Listing).count() == 2
    listing = session.get(Listing, data[0]["id"])
    assert listing.source == "rentcast"
    assert listing.zip_code == "28409"
    assert listing.lot_size_sqft == 21780
    assert listing.price == 875000


def test_ingest_all_zips_dedupes_unchanged_listings(session, monkeypatch):
    data = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(
        "canopy.ingest.fetch_sale_listings_for_zip", lambda zip_code: data
    )

    first = ingest_all_zips(session, zips=["28409"])
    second = ingest_all_zips(session, zips=["28409"])

    assert len(first) == 2
    assert len(second) == 0
    assert session.query(Listing).count() == 2


def test_ingest_all_zips_flags_price_change_as_changed(session, monkeypatch):
    data = json.loads(FIXTURE.read_text())
    monkeypatch.setattr(
        "canopy.ingest.fetch_sale_listings_for_zip", lambda zip_code: data
    )
    ingest_all_zips(session, zips=["28409"])

    updated = json.loads(FIXTURE.read_text())
    updated[0]["price"] = 825000
    monkeypatch.setattr(
        "canopy.ingest.fetch_sale_listings_for_zip", lambda zip_code: updated
    )

    changed = ingest_all_zips(session, zips=["28409"])

    assert len(changed) == 1
    assert changed[0].id == updated[0]["id"]
    assert changed[0].price == 825000
