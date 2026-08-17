"""Collate Zillow-sourced listings with matching RentCast rows.

RentCast is retired as the *primary* listings source (docs/ARCHITECTURE.md's
Appendix) but restored as a background-only weekly feed
(canopy/cli.py::run_rentcast_weekly, canopy/ingest.py) -- it never supplies
rating candidates, it exists purely to keep this module's matching pool
fresh. Zillow's alert emails don't carry everything RentCast does (no
explicit property type, no lot size, no year built, no MLS numbers; see
canopy/clients/zillow_email.py's module docstring for the confirmed gap
list). Where a Zillow-sourced listing's address matches a RentCast row,
this fills in what the RentCast side has and the Zillow side doesn't --
never the reverse, and never overwriting a value Zillow already provided.
Matched listings are flagged `collated_with_rentcast=True`, which
canopy.rating.get_batch uses to surface them first in the rating queue --
a listing with a more complete feature vector is worth rating sooner.

Address matching can't use a plain string-equality normalize (see
canopy/email_ingest.py::_normalize_address, which exists for a different
purpose -- deduping repeated Zillow emails about the *same* listing,
where formatting is internally consistent). RentCast and Zillow format
the same real address differently: RentCast abbreviates street suffixes
and appends the zip ("627 Jennings Dr, Wilmington, NC 28403"); Zillow
spells them out and omits it ("126 Parkwood Drive, Wilmington, NC").
_street_key collapses both to the same canonical form. Verified against
real ingested data (before the weekly feed was restored): 4/19 real
Zillow listings matched a RentCast row this way. Investigating the other
15 found the match rate was mostly a staleness artifact, not a matching-
logic gap -- every RentCast row had the exact same first_seen timestamp
(a one-time historical pull, frozen the moment ingestion was retired), so
anything listed after that pull couldn't possibly match yet. A couple of
misses are structural rather than timing (new-construction "plan"
listings with no fixed street address yet; one listing outside RentCast's
original target zips) -- those won't be fixed by freshness alone.
"""

import logging
import re

from sqlalchemy.orm import Session

from canopy.db.models import Listing

logger = logging.getLogger(__name__)

# USPS-style street-suffix aliases, spelled-out -> abbreviated. Covers the
# suffixes actually observed across real ingested addresses in this
# market; extend if a future mismatch turns up an unhandled one.
_SUFFIX_ALIASES = {
    "road": "rd", "rd": "rd",
    "drive": "dr", "dr": "dr",
    "lane": "ln", "ln": "ln",
    "place": "pl", "pl": "pl",
    "court": "ct", "ct": "ct",
    "street": "st", "st": "st",
    "circle": "cir", "cir": "cir",
    "avenue": "ave", "ave": "ave",
    "boulevard": "blvd", "blvd": "blvd",
    "trail": "trl", "trl": "trl",
    "terrace": "ter", "ter": "ter",
    "parkway": "pkwy", "pkwy": "pkwy",
    "crossing": "xing", "xing": "xing",
    "point": "pt", "pt": "pt",
    "highway": "hwy", "hwy": "hwy",
    "way": "way",
    "loop": "loop",
    "run": "run",
    "walk": "walk",
}
# Everything from a unit/suite/lot designator onward is dropped -- a
# RentCast row for "452 Racine Dr, Unit F303" and a Zillow row for the
# same building's "452 Racine Dr" should still key-match on the street
# address; unit-level precision isn't needed to identify the same parcel.
_UNIT_WORDS = {"apt", "unit", "ste", "suite", "lot", "bldg", "#"}
_NON_WORD_RE = re.compile(r"[^\w\s]")


def _street_key(formatted_address: str) -> str:
    first_segment = formatted_address.split(",")[0]
    tokens = _NON_WORD_RE.sub(" ", first_segment.lower()).split()
    out = []
    for token in tokens:
        if token in _UNIT_WORDS:
            break
        out.append(_SUFFIX_ALIASES.get(token, token))
    return " ".join(out)


# Listing model fields worth pulling from a matched RentCast row when the
# Zillow-sourced row doesn't already have them.
BACKFILL_FIELDS = [
    "lot_size_sqft", "year_built", "property_type", "county",
    "mls_name", "mls_number", "zip_code", "listed_date",
]
# Raw-payload keys canopy/features.py::_market_fields reads directly out
# of Listing.raw -- Zillow's parsed payload never has these (see
# canopy/clients/zillow_email.py), RentCast's always might.
_RAW_BACKFILL_KEYS = ["daysOnMarket", "hoa", "history"]


def _rentcast_index(session: Session) -> dict[str, list[Listing]]:
    index: dict[str, list[Listing]] = {}
    for row in session.query(Listing).filter(Listing.source == "rentcast"):
        index.setdefault(_street_key(row.formatted_address), []).append(row)
    return index


def backfill_from_rentcast(session: Session, listings: list[Listing] | None = None) -> list[Listing]:
    """For each given (or, if None, every) Zillow-sourced listing, find a
    RentCast row with a matching street address and copy over any
    BACKFILL_FIELDS/raw keys the Zillow row doesn't already have. Returns
    every listing touched -- either because a field was filled, or
    because a match was (re)confirmed and collated_with_rentcast needed
    setting for the first time -- so callers can recompute feature
    vectors for rows whose data actually changed."""
    rentcast_index = _rentcast_index(session)
    if not rentcast_index:
        return []

    query = session.query(Listing).filter(Listing.source == "zillow_email")
    if listings is not None:
        query = query.filter(Listing.id.in_([listing.id for listing in listings]))
    targets = query.all()

    changed: list[Listing] = []
    for zillow in targets:
        candidates = rentcast_index.get(_street_key(zillow.formatted_address))
        if not candidates:
            continue
        match = candidates[0]  # a street-key collision across multiple RentCast rows hasn't been observed

        filled: dict[str, object] = {}
        for field in BACKFILL_FIELDS:
            if getattr(zillow, field) is not None:
                continue
            value = getattr(match, field)
            if value is None:
                continue
            setattr(zillow, field, value)
            filled[field] = value

        raw = dict(zillow.raw or {})
        match_raw = match.raw or {}
        for key in _RAW_BACKFILL_KEYS:
            if raw.get(key) is not None:
                continue
            if match_raw.get(key) is not None:
                raw[key] = match_raw[key]
                filled[f"raw.{key}"] = match_raw[key]

        # A match with nothing left to fill (e.g. a re-run after an
        # earlier backfill already populated every gap field) still needs
        # collated_with_rentcast set -- the flag means "has a known
        # RentCast counterpart," not "this call changed something." Only
        # skip entirely when there's truly nothing new to record.
        if not filled and zillow.collated_with_rentcast:
            continue

        raw["rentcast_backfill_listing_id"] = match.id
        zillow.raw = raw
        zillow.collated_with_rentcast = True
        changed.append(zillow)
        if filled:
            logger.info("backfilled %s from rentcast %s: %s", zillow.id, match.id, sorted(filled))
        else:
            logger.info("flagged %s as collated with rentcast %s (already up to date)", zillow.id, match.id)

    if changed:
        session.commit()
    return changed
