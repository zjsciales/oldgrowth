import datetime as dt

from canopy.db.models import Listing
from canopy.rentcast_backfill import _street_key, backfill_from_rentcast


def _rentcast(id, address, **overrides):
    fields = dict(
        id=id, source="rentcast", formatted_address=address,
        city="Wilmington", state="NC", status="Active",
        lot_size_sqft=10000.0, year_built=1990, property_type="Single Family",
        county="New Hanover", mls_name="NCRMLS", mls_number="100123456",
        zip_code="28403", listed_date=dt.datetime(2026, 1, 1),
        raw={"daysOnMarket": 12, "hoa": {"fee": 50}, "history": {"2026-01-01": {"price": 400000}}},
    )
    fields.update(overrides)
    return Listing(**fields)


def _zillow(id, address, **overrides):
    fields = dict(
        id=id, source="zillow_email", source_listing_id=id.split("-", 1)[1],
        normalized_address=address.lower(), formatted_address=address,
        city="Wilmington", state="NC", status="Active",
        raw={"bedrooms": 3.0, "bathrooms": 2.0},
    )
    fields.update(overrides)
    return Listing(**fields)


def test_street_key_normalizes_suffix_and_drops_unit():
    assert _street_key("627 Jennings Dr, Wilmington, NC 28403") == "627 jennings dr"
    assert _street_key("627 Jennings Drive, Wilmington, NC") == "627 jennings dr"
    assert _street_key("452 Racine Dr, Unit F303, Wilmington, NC 28403") == "452 racine dr"


def test_backfill_fills_gaps_without_overwriting_zillow_fields(session):
    session.add(_rentcast("rentcast-1", "627 Jennings Dr, Wilmington, NC 28403"))
    session.add(_zillow("zillow-99", "627 Jennings Drive, Wilmington, NC", price=450000))
    session.commit()

    changed = backfill_from_rentcast(session)

    assert len(changed) == 1
    listing = changed[0]
    assert listing.lot_size_sqft == 10000.0
    assert listing.year_built == 1990
    assert listing.property_type == "Single Family"
    assert listing.mls_number == "100123456"
    assert listing.county == "New Hanover"
    assert listing.raw["daysOnMarket"] == 12
    assert listing.raw["hoa"] == {"fee": 50}
    assert listing.raw["rentcast_backfill_listing_id"] == "rentcast-1"
    # never overwritten -- Zillow's own value wins
    assert listing.price == 450000


def test_backfill_skips_fields_zillow_already_has(session):
    session.add(_rentcast("rentcast-1", "1 Main St, Wilmington, NC 28403", year_built=1950))
    session.add(_zillow("zillow-1", "1 Main Street, Wilmington, NC", year_built=2020))
    session.commit()

    backfill_from_rentcast(session)

    listing = session.query(Listing).filter_by(id="zillow-1").one()
    assert listing.year_built == 2020  # Zillow's own value, not RentCast's


def test_backfill_no_match_leaves_listing_unchanged(session):
    session.add(_rentcast("rentcast-1", "1 Main St, Wilmington, NC 28403"))
    session.add(_zillow("zillow-1", "9 Nonexistent Ave, Wilmington, NC"))
    session.commit()

    changed = backfill_from_rentcast(session)

    assert changed == []


def test_backfill_can_scope_to_a_subset_of_listings(session):
    session.add(_rentcast("rentcast-1", "1 Main St, Wilmington, NC 28403"))
    session.add(_rentcast("rentcast-2", "2 Oak Rd, Wilmington, NC 28403"))
    z1 = _zillow("zillow-1", "1 Main Street, Wilmington, NC")
    z2 = _zillow("zillow-2", "2 Oak Road, Wilmington, NC")
    session.add(z1)
    session.add(z2)
    session.commit()

    changed = backfill_from_rentcast(session, [z1])

    assert [listing.id for listing in changed] == ["zillow-1"]
    assert session.query(Listing).filter_by(id="zillow-2").one().lot_size_sqft is None
