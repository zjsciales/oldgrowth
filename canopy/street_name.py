"""Extracts a display-ready street name from a listing's mailing address.

Distinct from canopy/rentcast_backfill.py::_street_key, which normalizes
for address *matching* (lowercased, suffix-abbreviated, unit-stripped) --
this preserves real casing/spacing for display. Also distinct from
canopy/clients/nhc_gis.py's per-edge road names (real GIS STREET/TYPE/DIR
fields on whichever road segment actually touches a given compass side):
this is "the street named on the mailing address," which is what a human
means by "what street is this house on" and doesn't require any GIS call.
"""

import re

_LEADING_NUMBER_RE = re.compile(r"^\s*[\d\-/]+[A-Za-z]?\s+")


def extract_street_name(formatted_address: str | None) -> str | None:
    """'126 Parkwood Drive' from either RentCast-style
    ('627 Jennings Dr, Wilmington, NC 28403') or Zillow-style
    ('126 Parkwood Drive, Wilmington, NC') formatted_address strings."""
    if not formatted_address:
        return None
    first_segment = formatted_address.split(",")[0].strip()
    street = _LEADING_NUMBER_RE.sub("", first_segment).strip()
    return street or None
