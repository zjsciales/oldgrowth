"""CLI entrypoints. Usage: python -m canopy.cli <command>"""

import argparse
import logging

from canopy.db.models import Listing, Parcel, Score
from canopy.db.session import SessionLocal
from canopy.digest import send_digest
from canopy.enrich import enrich_listings
from canopy.filter import filter_listings
from canopy.ingest import ingest_all_zips
from canopy.scoring import score_listings
from canopy.subagent import run_subagent_on_candidates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _unenriched_backlog(session) -> list[Listing]:
    """Listings that were ingested but never finished GIS enrichment --
    e.g. a prior run crashed mid-Stage-2. `changed` from ingest_all_zips
    won't reliably catch these on the next run (it's keyed on
    status/price/last_seen_date, not on pipeline completeness), so a
    crash here could otherwise leave a listing stuck forever."""
    enriched_ids = {
        listing_id for (listing_id,) in session.query(Parcel.listing_id).filter(Parcel.enriched_at.isnot(None))
    }
    return session.query(Listing).filter(~Listing.id.in_(enriched_ids)).all()


def run_weekly(dry_run: bool = False) -> None:
    session = SessionLocal()
    try:
        logger.info("=== Stage 1: ingest ===")
        changed = ingest_all_zips(session)
        logger.info("%d new/changed listings", len(changed))

        backlog = _unenriched_backlog(session)
        if backlog:
            logger.info("%d listings from prior runs never finished enrichment, including them", len(backlog))

        to_process = list({listing.id: listing for listing in [*changed, *backlog]}.values())
        if not to_process:
            logger.info("nothing new this week, exiting")
            return

        logger.info("=== Stage 2: GIS enrichment ===")
        enrich_listings(session, to_process)

        logger.info("=== Stage 3: canopy scoring ===")
        score_listings(session, to_process)

        logger.info("=== Stage 4: rule-based filter ===")
        candidates = filter_listings(session, to_process)
        logger.info("%d candidates passed the filter", len(candidates))
        if not candidates:
            logger.info("no candidates this week, exiting")
            return

        logger.info("=== Stage 5: Claude sub-agent ===")
        already_evaluated_ids = {
            score.listing_id for score in session.query(Score).filter(Score.subagent_rationale.isnot(None))
        }
        unevaluated_candidates = [c for c in candidates if c.id not in already_evaluated_ids]
        if len(unevaluated_candidates) < len(candidates):
            logger.info(
                "%d candidates already evaluated by a prior run, skipping",
                len(candidates) - len(unevaluated_candidates),
            )
        run_subagent_on_candidates(session, unevaluated_candidates)

        logger.info("=== Stage 6: digest ===")
        html = send_digest(session, candidates, dry_run=dry_run)
        if dry_run:
            logger.info("dry-run digest HTML:\n%s", html)
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="canopy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    weekly = subparsers.add_parser("run-weekly", help="Run the full weekly pipeline")
    weekly.add_argument(
        "--dry-run", action="store_true",
        help="Run the full pipeline but skip sending the email (logs the digest instead)",
    )

    args = parser.parse_args()
    if args.command == "run-weekly":
        run_weekly(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
