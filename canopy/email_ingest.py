"""Stage 1 (email-sourced): poll the Gmail label for unprocessed Zillow
alert emails, parse each, geocode addresses via the already-integrated
Mapbox client, upsert into Postgres, and return the set of listings that
are new or changed since last run. Replaces canopy/ingest.py (RentCast)."""

import datetime as dt
import email as email_lib
import hashlib
import logging
import re

from sqlalchemy.orm import Session

from canopy.clients import gmail
from canopy.clients.mapbox import MapboxError, geocode_address
from canopy.clients.zillow_email import ZillowParseError, parse_zillow_alert_email
from canopy.config import TARGET_ZIPS
from canopy.db.models import EmailIngestLog, Listing

logger = logging.getLogger(__name__)

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
# Mapbox's geocoding v6 full_address always ends "..., <State> <ZIP>,
# United States" for a real street address within WILMINGTON_METRO_BBOX
# (confirmed live) -- anchored to "United States" so this never matches
# the street number at the start of the string instead.
_ZIP_RE = re.compile(r"(\d{5})(?=,\s*United States)")


def _normalize_address(formatted_address: str) -> str:
    return _NORMALIZE_RE.sub(" ", formatted_address.lower()).strip()


def _find_existing(session: Session, zpid: str | None, normalized_address: str) -> Listing | None:
    if zpid is not None:
        existing = session.query(Listing).filter_by(source_listing_id=zpid, source="zillow_email").one_or_none()
        if existing is not None:
            return existing
    return session.query(Listing).filter_by(normalized_address=normalized_address).one_or_none()


def _listing_id(zpid: str | None, normalized_address: str) -> str:
    if zpid is not None:
        return f"zillow-{zpid}"
    digest = hashlib.sha1(normalized_address.encode("utf-8")).hexdigest()[:16]
    return f"zillow-addr-{digest}"


def _geocode(formatted_address: str) -> tuple[float | None, float | None, str | None]:
    try:
        geocoded = geocode_address(formatted_address)
    except MapboxError:
        logger.exception("geocoding failed for %r, ingesting without coordinates", formatted_address)
        return None, None, None
    if geocoded is None:
        logger.warning("no geocode match for %r, ingesting without coordinates", formatted_address)
        return None, None, None
    lat, lon, resolved_address = geocoded
    zip_match = _ZIP_RE.search(resolved_address)
    return lat, lon, (zip_match.group(1) if zip_match else None)


def _upsert_listing(session: Session, parsed: dict, received_at: dt.datetime) -> tuple[Listing, bool]:
    """Returns (listing, changed). Field-presence-aware: a parsed value of
    None never overwrites an existing non-None value -- an alert email
    (e.g. a price-drop notice) won't necessarily restate every field, and
    RentCast-style unconditional clobbering would silently destroy
    previously-known data on a partial payload."""
    normalized = _normalize_address(parsed["formatted_address"])
    existing = _find_existing(session, parsed["zpid"], normalized)

    if existing is None:
        listing = Listing(
            id=_listing_id(parsed["zpid"], normalized),
            source="zillow_email",
            source_listing_id=parsed["zpid"],
            normalized_address=normalized,
            formatted_address=parsed["formatted_address"],
            city=parsed["city"] or "",
            state=parsed["state"],
            status="Active",
            raw=parsed,
        )
        session.add(listing)
        changed = True
    else:
        listing = existing
        changed = False

    lat, lon, zip_code = _geocode(parsed["formatted_address"])

    field_values = {
        "price": parsed.get("price"),
        "square_footage": parsed.get("square_footage"),
        "latitude": lat,
        "longitude": lon,
        "zip_code": zip_code,
        "property_type": "New Construction" if parsed.get("is_new_construction") else None,
        "photo_url": parsed.get("photo_url"),
    }
    for field, value in field_values.items():
        if value is None:
            continue
        if getattr(listing, field) != value:
            changed = True
        setattr(listing, field, value)

    if listing.zip_code and listing.zip_code not in TARGET_ZIPS:
        logger.warning(
            "zillow_email: %s is outside TARGET_ZIPS (zip=%s) -- flagged out of area",
            listing.formatted_address, listing.zip_code,
        )

    raw = dict(listing.raw or {})
    raw.update({k: v for k, v in parsed.items() if v is not None})
    listing.raw = raw

    listing.last_seen_date = received_at
    return listing, changed


def ingest_from_email(session: Session) -> list[Listing]:
    changed: list[Listing] = []

    for uid, raw_message in gmail.fetch_unprocessed_messages():
        try:
            message_id = email_lib.message_from_bytes(raw_message).get("Message-ID") or uid.decode()
        except Exception:
            message_id = uid.decode()

        if session.query(EmailIngestLog).filter_by(message_id=message_id).one_or_none() is not None:
            gmail.mark_processed(uid)
            continue

        received_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
        parse_errors: list[str] = []
        parsed_listings: list[dict] = []
        try:
            parsed_listings = parse_zillow_alert_email(raw_message)
        except ZillowParseError as exc:
            parse_errors.append(str(exc))
            logger.warning("zillow_email: failed to parse message %s: %s", message_id, exc)

        for parsed in parsed_listings:
            try:
                listing, is_changed = _upsert_listing(session, parsed, received_at)
                if is_changed:
                    changed.append(listing)
            except Exception as exc:  # noqa: BLE001 -- one bad block must not sink the whole email
                parse_errors.append(f"{parsed.get('formatted_address', '?')}: {exc}")
                logger.exception("zillow_email: failed to upsert a listing block in message %s", message_id)

        session.add(EmailIngestLog(
            message_id=message_id, source="zillow_email", received_at=received_at,
            listings_found=len(parsed_listings), listings_parsed_ok=len(parsed_listings) - len(parse_errors),
            parse_errors=parse_errors or None,
        ))
        session.commit()
        gmail.mark_processed(uid)
        logger.info(
            "zillow_email: message %s -> %d listings found, %d errors",
            message_id, len(parsed_listings), len(parse_errors),
        )

    return changed
