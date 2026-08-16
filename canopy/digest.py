"""Weekly digest email. Built from the preference model's digest plan
(canopy/model.py::compute_digest_slots), not a rule-based filter's
pass/fail list -- every section is ranked, never gated, per
SCORING_MODEL.md §6's 70/20/10 top-ranked/uncertain/wildcard split.

Note on links: see canopy/listing_links.py for why these are plain
search/reference links rather than scraped or guessed deep-link URLs.
"""

import datetime as dt
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from canopy.config import DIGEST_TO_EMAIL, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER
from canopy.db.models import DigestLog, Listing, ListingFeatures, Parcel, Score
from canopy.listing_links import NHC_RECORDS_SEARCH_URL, listing_search_url, satellite_url

logger = logging.getLogger(__name__)

SECTION_TITLES = {
    "top_ranked": "Top ranked",
    "uncertain": "Still deciding -- rating these helps the model most",
    "wildcard": "Wildcard",
}


def _listing_row_html(session: Session, detail: dict) -> str:
    listing_id = detail["listing_id"]
    listing = session.get(Listing, listing_id)
    if listing is None:
        return ""
    parcel = session.query(Parcel).filter_by(listing_id=listing_id).one_or_none()
    features = (
        session.query(ListingFeatures)
        .filter_by(listing_id=listing_id)
        .order_by(ListingFeatures.computed_at.desc())
        .first()
    )
    score = session.query(Score).filter_by(listing_id=listing_id).one_or_none()

    maps_url = satellite_url(listing.latitude, listing.longitude)
    search_url = listing_search_url(listing.formatted_address)
    price = f"${listing.price:,.0f}" if listing.price else "price unknown"
    parcel_id = parcel.parcel_id if parcel else "unknown"
    canopy_pct = features.parcel_canopy_pct if features else None
    canopy_text = f"{canopy_pct:.0f}% canopy cover" if canopy_pct is not None else "canopy unknown"
    rationale = (score.subagent_rationale if score else None) or ""
    maps_link = f' &middot; <a href="{maps_url}">Satellite view</a>' if maps_url else ""

    return f"""
    <div style="margin-bottom: 20px; padding-bottom: 20px; border-bottom: 1px solid #ddd;">
      <h3 style="margin: 0 0 4px;">{listing.formatted_address}</h3>
      <p style="margin: 0 0 8px; color: #555;">{price} &middot; {canopy_text}</p>
      <p style="margin: 0 0 8px;">{rationale}</p>
      <p style="margin: 0; font-size: 0.9em;">
        <a href="{search_url}">Search listing (photos, details)</a>{maps_link} &middot;
        <a href="{NHC_RECORDS_SEARCH_URL}">County records search</a> (PID: {parcel_id})
      </p>
    </div>
    """


def _section_html(session: Session, title: str, details: list[dict]) -> str:
    if not details:
        return ""
    rows = "".join(_listing_row_html(session, d) for d in details)
    return f'<h2 style="margin-top: 32px;">{title}</h2>{rows}'


def _disagreement_section_html(session: Session, plan: dict) -> str:
    if not plan["ready"]:
        return (
            '<h2 style="margin-top: 32px;">You two disagree about these</h2>'
            '<p style="color: #555;">Still calibrating -- this section unlocks '
            "once you've both rated a few dozen homes.</p>"
        )
    if not plan["disagreements"]:
        return ""
    rows = "".join(_listing_row_html(session, d) for d in plan["disagreements"])
    return (
        '<h2 style="margin-top: 32px;">You two disagree about these</h2>'
        '<p style="color: #555;">The most productive conversations in this whole '
        "process -- the model can't resolve a real difference in taste, only "
        f"locate it.</p>{rows}"
    )


def render_digest_html(session: Session, plan: dict) -> str:
    if not plan["ready"]:
        return (
            '<html><body style="font-family: sans-serif; max-width: 640px; margin: 0 auto;">'
            "<h2>Canopy Weekly Digest</h2>"
            "<p>Still calibrating -- rate a few dozen homes each before the ranked "
            "digest kicks in.</p>"
            "</body></html>"
        )

    sections = "".join(
        _section_html(session, SECTION_TITLES[key], plan[key])
        for key in ("top_ranked", "uncertain", "wildcard")
    )
    sections += _disagreement_section_html(session, plan)

    total = len(plan["top_ranked"]) + len(plan["uncertain"]) + len(plan["wildcard"])
    return (
        '<html><body style="font-family: sans-serif; max-width: 640px; margin: 0 auto;">'
        "<h2>Canopy Weekly Digest</h2>"
        f'<p>{total} listing{"s" if total != 1 else ""} this week.</p>'
        f"{sections}"
        "</body></html>"
    )


def send_digest(session: Session, plan: dict, dry_run: bool = False) -> str:
    """Builds and sends the digest from a compute_digest_slots() plan.
    Returns the rendered HTML (useful for dry-run inspection).

    DigestLog is a plain audit log, not a suppression filter -- a listing
    can legitimately resurface if its rank or uncertainty changes week to
    week, which is correct for a ranking system even though re-sending
    would have been wrong for the old fixed pass/fail filter."""
    html = render_digest_html(session, plan)

    listing_ids: list[str] = []
    if plan["ready"]:
        for key in ("top_ranked", "uncertain", "wildcard"):
            listing_ids += [d["listing_id"] for d in plan[key]]

    if dry_run:
        logger.info("dry-run: digest not sent, %d listings", len(listing_ids))
        return html

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Canopy Weekly Digest - {dt.date.today().isoformat()}"
    msg["From"] = SMTP_USER
    msg["To"] = DIGEST_TO_EMAIL
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [DIGEST_TO_EMAIL], msg.as_string())

    for listing_id in listing_ids:
        session.add(DigestLog(listing_id=listing_id))
    session.commit()

    logger.info("digest sent to %s: %d listings", DIGEST_TO_EMAIL, len(listing_ids))
    return html
