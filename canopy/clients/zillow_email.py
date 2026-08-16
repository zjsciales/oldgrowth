"""Parser for Zillow saved-search/recommendation alert emails -- the new
Stage 1 listings source, replacing RentCast (see docs/CLAUDE.md).

Parses two MIME parts, for two different reasons:

- **`text/plain`** for every numeric/text field (price, beds/baths/sqft,
  address, a zpid embedded in the "View this listing" URL). Two real alert
  emails (a "recommendations" digest and a "saved search" instant update,
  see tests/fixtures/zillow_alert_*.eml) were used to design this: both
  carry a full text/plain alternative with everything needed, and it's
  dramatically simpler and more robust than fighting Zillow's obfuscated,
  heavily-styled quoted-printable HTML (inline CSS, tracking pixels,
  VML/MSO conditionals) for the same information. Deliberate deviation from
  the original BeautifulSoup-on-HTML plan, made once real samples showed
  the plain-text part was sufficient for these fields.
- **`text/html`**, narrowly, for the one thing the plain-text part doesn't
  carry at all: the listing photo. Each property card's real photo is a
  table-cell `background="https://photos.zillowstatic.com/..."` attribute
  (an HTML-email pattern for cross-client image rendering), not a plain
  `<img src>` -- the one `<img>` tag that does appear per card is a
  generic, non-property-specific "MLS" provider badge (confirmed: it's
  the exact same URL/hash repeated across every listing in a message,
  unlike the per-card background images, which are all distinct). Each
  photo is matched to its listing by finding the zpid that appears shortly
  after it in the HTML -- verified 12/12 correct against both real
  fixtures, so this is a real correlation, not a guess.

Known gap (confirmed against both real samples, not assumed): neither alert
type states an explicit property-type field anywhere -- only "New
construction | New" appears as a label on new-construction listings. So
canopy.rating.is_hard_excluded's Condo/Apartment branch simply can't fire
pre-ingest for email-sourced listings; they flow through the pipeline like
anything else until a rater manually tags them out.
"""

import re
from email import message_from_bytes
from email.message import Message
from email.policy import default as email_policy

STAT_BLOCK_RE = re.compile(
    r"(?P<beds>\d+(?:\.\d+)?)\s*bd\s*\|\s*(?P<baths>\d+(?:\.\d+)?)\s*ba\s*\|\s*(?P<sqft>[\d,]+)\s*sqft"
)
PRICE_RE = re.compile(
    r"\$(?P<price>[\d,]+)(?:\s*\|\s*Price cut:\s*\$(?P<cut>[\d,]+K?)\s*\(?(?P<cut_date>[^)\n]*)\)?)?"
)
# Deliberately permissive on how many comma-separated segments precede the
# state: "6803 Myrtle Grove Road, Wilmington, NC" (2 segments) and "Mimosa
# Plan, Riverlights, Wilmington, NC" (3 segments -- development name +
# subdivision + city, seen on new-construction listings) both need to match.
ADDRESS_RE = re.compile(r"^(?P<address>[^\n]+,\s*NC)\s*$", re.MULTILINE)
ZPID_RE = re.compile(r"(\d+)_zpid")
VIEW_LISTING_RE = re.compile(r"View this listing\s*-\s*\n(?P<url>\S+)")
NEW_CONSTRUCTION_RE = re.compile(r"new construction", re.IGNORECASE)
OPEN_HOUSE_RE = re.compile(r"open house", re.IGNORECASE)
PHOTO_BACKGROUND_RE = re.compile(r'background="(https://photos\.zillowstatic\.com/[^"]+)"')

# How far back from a price line to look for a "New construction | New" /
# "For sale" style label -- generous enough to span a blank line, tight
# enough not to bleed into the previous listing block's own label.
LABEL_WINDOW_CHARS = 120

# How far forward from a photo's background-image attribute to look for
# that same card's zpid link -- generous enough to reach it (the card's
# address/price/CTA markup sits between them) but tight enough not to
# reach into the next card's zpid.
PHOTO_ZPID_LOOKAHEAD_CHARS = 2000


class ZillowParseError(RuntimeError):
    pass


def _extract_photo_urls_by_zpid(msg: Message) -> dict[str, str]:
    html_part = msg.get_body(preferencelist=("html",))
    if html_part is None:
        return {}
    html = html_part.get_content()

    photos: dict[str, str] = {}
    for match in PHOTO_BACKGROUND_RE.finditer(html):
        window = html[match.end():match.end() + PHOTO_ZPID_LOOKAHEAD_CHARS]
        zpid_match = ZPID_RE.search(window)
        if zpid_match:
            photos.setdefault(zpid_match.group(1), match.group(1))
    return photos


def _brokerage(post_text: str, address_end: int, view_match: re.Match | None) -> str | None:
    window_end = view_match.start() if view_match else len(post_text)
    window = post_text[address_end:window_end]
    lines = [line.strip() for line in window.splitlines() if line.strip()]
    lines = [
        line for line in lines
        if not OPEN_HOUSE_RE.search(line)
        and not re.match(r"^[A-Za-z]{3}\.?\s+\d", line)  # "Thu. 5:30pm-6:30pm"
    ]
    return lines[-1] if lines else None


def parse_zillow_alert_email(raw_message: bytes) -> list[dict]:
    """Returns one dict per listing block found in the email. Raises
    ZillowParseError only when the message has no usable text/plain part or
    no listing blocks at all -- a single malformed block within an
    otherwise-good email is silently skipped (best-effort, matches
    EmailIngestLog's per-block parse_errors tracking in email_ingest.py)."""
    msg = message_from_bytes(raw_message, policy=email_policy)
    text_part = msg.get_body(preferencelist=("plain",))
    if text_part is None:
        raise ZillowParseError("no text/plain part found in message")
    text = text_part.get_content()
    photo_urls_by_zpid = _extract_photo_urls_by_zpid(msg)

    listings: list[dict] = []
    stat_matches = list(STAT_BLOCK_RE.finditer(text))

    for i, stat_match in enumerate(stat_matches):
        block_start = stat_matches[i - 1].end() if i > 0 else 0
        block_end = stat_matches[i + 1].start() if i + 1 < len(stat_matches) else len(text)
        pre_text = text[block_start:stat_match.start()]
        post_text = text[stat_match.end():block_end]

        price_match = None
        for m in PRICE_RE.finditer(pre_text):
            price_match = m  # last (closest-preceding) price line wins
        if price_match is None:
            continue

        address_match = ADDRESS_RE.search(post_text)
        if address_match is None:
            continue

        view_match = VIEW_LISTING_RE.search(post_text)
        zpid = None
        if view_match:
            zpid_match = ZPID_RE.search(view_match.group("url"))
            if zpid_match:
                zpid = zpid_match.group(1)

        label_window = pre_text[max(0, price_match.start() - LABEL_WINDOW_CHARS):price_match.start()]

        address_parts = [p.strip() for p in address_match.group("address").split(",")]
        city = address_parts[-2] if len(address_parts) >= 2 else None

        cut_raw = price_match.group("cut")
        listings.append({
            "zpid": zpid,
            "price": int(price_match.group("price").replace(",", "")),
            "price_cut": cut_raw is not None,
            "bedrooms": float(stat_match.group("beds")),
            "bathrooms": float(stat_match.group("baths")),
            "square_footage": int(stat_match.group("sqft").replace(",", "")),
            "formatted_address": address_match.group("address").strip(),
            "city": city,
            "state": "NC",
            "brokerage": _brokerage(post_text, address_match.end(), view_match),
            "is_new_construction": bool(NEW_CONSTRUCTION_RE.search(label_window)),
            "has_open_house": bool(OPEN_HOUSE_RE.search(post_text[:view_match.start() if view_match else len(post_text)])),
            "detail_url": view_match.group("url") if view_match else None,
            "photo_url": photo_urls_by_zpid.get(zpid) if zpid else None,
        })

    if not listings:
        raise ZillowParseError("no listing blocks found in message")
    return listings
