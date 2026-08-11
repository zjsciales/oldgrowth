"""Stage 1: pull sale listings for all target zips, upsert into Postgres,
and return the set of listings that are new or changed since last run."""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from canopy.clients.rentcast import fetch_sale_listings_for_zip
from canopy.config import TARGET_ZIPS
from canopy.db.models import Listing

logger = logging.getLogger(__name__)


def _parse_date(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Store naive UTC — DB columns are naive, and comparing naive vs
    # aware datetimes with `!=` silently returns True instead of raising,
    # which broke change-detection in ingest_all_zips.
    return parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)


def _listing_from_raw(raw: dict) -> Listing:
    return Listing(
        id=raw["id"],
        formatted_address=raw.get("formattedAddress", ""),
        city=raw.get("city", ""),
        state=raw.get("state", ""),
        zip_code=raw.get("zipCode", ""),
        county=raw.get("county"),
        latitude=raw.get("latitude"),
        longitude=raw.get("longitude"),
        property_type=raw.get("propertyType"),
        lot_size_sqft=raw.get("lotSize"),
        square_footage=raw.get("squareFootage"),
        year_built=raw.get("yearBuilt"),
        status=raw.get("status", "Active"),
        price=raw.get("price"),
        listed_date=_parse_date(raw.get("listedDate")),
        removed_date=_parse_date(raw.get("removedDate")),
        last_seen_date=_parse_date(raw.get("lastSeenDate")),
        mls_name=raw.get("mlsName"),
        mls_number=raw.get("mlsNumber"),
        raw=raw,
    )


def ingest_all_zips(session: Session, zips: list[str] | None = None) -> list[Listing]:
    """Fetch + upsert listings for every target zip. Returns new-or-changed listings."""
    zips = zips if zips is not None else TARGET_ZIPS
    changed: list[Listing] = []

    for zip_code in zips:
        raw_listings = fetch_sale_listings_for_zip(zip_code)
        logger.info("rentcast: %s listings for zip %s", len(raw_listings), zip_code)

        for raw in raw_listings:
            listing_id = raw.get("id")
            if not listing_id:
                continue

            existing = session.get(Listing, listing_id)
            incoming = _listing_from_raw(raw)

            if existing is None:
                session.add(incoming)
                changed.append(incoming)
                continue

            is_changed = (
                existing.status != incoming.status
                or existing.price != incoming.price
                or existing.last_seen_date != incoming.last_seen_date
            )
            for field in (
                "formatted_address", "city", "state", "zip_code", "county",
                "latitude", "longitude", "property_type", "lot_size_sqft",
                "square_footage", "year_built", "status", "price",
                "listed_date", "removed_date", "last_seen_date",
                "mls_name", "mls_number", "raw",
            ):
                setattr(existing, field, getattr(incoming, field))

            if is_changed:
                changed.append(existing)

    session.commit()
    return changed
