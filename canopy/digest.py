"""Stage 6: weekly digest email.

Note on links: RentCast's sale-listings response has no photo or public
MLS-listing URL field (confirmed against their API docs), and per
docs/CLAUDE.md we don't scrape Zillow/Redfin/Realtor.com for one. Each
digest entry instead links to Google Maps (satellite, from lat/long) and
New Hanover County's public tax records search (by PID) -- both real,
working links, not guessed deep-link formats.
"""

import datetime as dt
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from canopy.config import DIGEST_TO_EMAIL, SMTP_HOST, SMTP_PASS, SMTP_PORT, SMTP_USER
from canopy.db.models import DigestLog, Listing, Parcel, Score

logger = logging.getLogger(__name__)

NHC_RECORDS_SEARCH_URL = "https://tax.nhcgov.com/436/Records-Search"


def _candidate_html(listing: Listing, parcel: Parcel | None, score: Score) -> str:
    maps_url = f"https://www.google.com/maps/@{listing.latitude},{listing.longitude},19z/data=!3m1!1e3"
    price = f"${listing.price:,.0f}" if listing.price else "price unknown"
    parcel_id = parcel.parcel_id if parcel else "unknown"

    return f"""
    <div style="margin-bottom: 24px; padding-bottom: 24px; border-bottom: 1px solid #ddd;">
      <h3 style="margin: 0 0 4px;">{listing.formatted_address}</h3>
      <p style="margin: 0 0 8px; color: #555;">{price} &middot; {listing.lot_size_sqft or "?"} sqft lot
        &middot; built {listing.year_built or "?"} &middot; {score.canopy_pct:.0f}% canopy cover</p>
      <p style="margin: 0 0 8px;">{score.subagent_rationale or ""}</p>
      <p style="margin: 0; font-size: 0.9em;">
        <a href="{maps_url}">Satellite view</a> &middot;
        <a href="{NHC_RECORDS_SEARCH_URL}">County records search</a> (PID: {parcel_id})
      </p>
    </div>
    """


def render_digest_html(candidates: list[tuple[Listing, Parcel | None, Score]]) -> str:
    if not candidates:
        return "<p>No new candidates matched this week's criteria.</p>"

    body = "".join(_candidate_html(listing, parcel, score) for listing, parcel, score in candidates)
    return f"""
    <html><body style="font-family: sans-serif; max-width: 640px; margin: 0 auto;">
      <h2>Canopy Weekly Digest</h2>
      <p>{len(candidates)} new candidate{"s" if len(candidates) != 1 else ""} this week.</p>
      {body}
    </body></html>
    """


def send_digest(session: Session, candidates: list[Listing], dry_run: bool = False) -> str:
    """Builds and sends the digest for the given candidates. Returns the
    rendered HTML (useful for dry-run inspection or the test digest)."""
    rows = []
    for listing in candidates:
        parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
        score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()
        if score is None:
            continue
        rows.append((listing, parcel, score))

    html = render_digest_html(rows)

    if dry_run:
        logger.info("dry-run: digest not sent, %d candidates", len(rows))
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

    for listing, _, _ in rows:
        session.add(DigestLog(listing_id=listing.id))
    session.commit()

    logger.info("digest sent to %s: %d candidates", DIGEST_TO_EMAIL, len(rows))
    return html
