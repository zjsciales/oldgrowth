"""CLI entrypoints. Usage: python -m canopy.cli <command>"""

import argparse
import logging

from canopy.config import EXCLUDED_PROPERTY_TYPES
from canopy.db.models import Listing, ListingFeatures, Parcel, Rater
from canopy.db.session import SessionLocal
from canopy.digest import send_digest
from canopy.enrich import enrich_listings
from canopy.features import FEATURE_SET_VERSION, compute_features_for_listings
from canopy.ingest import ingest_all_zips
from canopy.model import compute_digest_slots, fit_model
from canopy.model import score_listings as score_preferences
from canopy.scoring import score_listings as score_canopy


def _excluding_property_types(listings: list[Listing]) -> list[Listing]:
    """Property types that are never candidates at all (e.g. Condo) skip
    every downstream stage -- GIS enrichment, canopy/raster scoring,
    feature computation, and (most importantly for cost) the lazy vision
    pass, which only ever runs on listings that reach the rating UI as
    candidates. Still ingested/stored (cheap, keeps market visibility),
    just never processed further."""
    return [listing for listing in listings if listing.property_type not in EXCLUDED_PROPERTY_TYPES]

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
    backlog = session.query(Listing).filter(~Listing.id.in_(enriched_ids)).all()
    return _excluding_property_types(backlog)


def _unfeatured_backlog(session) -> list[Listing]:
    """Same idea as _unenriched_backlog, one stage later: listings that
    were enriched/scored but never got a feature vector computed for the
    current FEATURE_SET_VERSION -- e.g. a crash mid-Stage-4."""
    featured_ids = {
        listing_id for (listing_id,) in
        session.query(ListingFeatures.listing_id).filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
    }
    backlog = session.query(Listing).filter(~Listing.id.in_(featured_ids)).all()
    return _excluding_property_types(backlog)


def run_weekly(dry_run: bool = False) -> None:
    session = SessionLocal()
    try:
        logger.info("=== Stage 1: ingest ===")
        changed = ingest_all_zips(session)
        logger.info("%d new/changed listings", len(changed))
        changed = _excluding_property_types(changed)

        enrich_backlog = _unenriched_backlog(session)
        # checked upfront, before any stage runs -- a listing stuck only
        # at Stage 4 (already enriched, never featured) has nothing in
        # `changed` or `enrich_backlog` to keep it from being missed by
        # the early-exit check below
        feature_backlog = _unfeatured_backlog(session)

        if not changed and not enrich_backlog and not feature_backlog:
            logger.info("nothing new this week, exiting")
            return

        if enrich_backlog:
            logger.info("%d listings from prior runs never finished enrichment, including them", len(enrich_backlog))
        to_enrich = list({listing.id: listing for listing in [*changed, *enrich_backlog]}.values())

        logger.info("=== Stage 2: GIS enrichment ===")
        enrich_listings(session, to_enrich)

        logger.info("=== Stage 3: canopy scoring ===")
        score_canopy(session, to_enrich)

        logger.info("=== Stage 4: feature vectors ===")
        if feature_backlog:
            logger.info("%d listings never got a feature vector, including them", len(feature_backlog))
        to_feature = list({listing.id: listing for listing in [*to_enrich, *feature_backlog]}.values())
        compute_features_for_listings(session, to_feature)

        raters = session.query(Rater).order_by(Rater.id).all()
        if len(raters) != 2:
            logger.warning(
                "expected exactly 2 raters for joint scoring, found %d -- skipping model refit/digest",
                len(raters),
            )
            return
        rater_a, rater_b = raters[0].id, raters[1].id

        logger.info("=== Stage 5: refit preference models (%s, %s) ===", rater_a, rater_b)
        for rater_id in (rater_a, rater_b):
            model_run = fit_model(session, rater_id)
            score_preferences(session, model_run)
            logger.info("%s: n_pairs=%d holdout_accuracy=%s", rater_id, model_run.n_pairs, model_run.holdout_accuracy)

        logger.info("=== Stage 6: digest ===")
        plan = compute_digest_slots(session, rater_a, rater_b)
        html = send_digest(session, plan, dry_run=dry_run)
        if dry_run:
            logger.info("dry-run digest HTML:\n%s", html)
    finally:
        session.close()


def compute_features() -> None:
    """Standalone Stage 4 (features) runner, independent of run_weekly --
    handy for backfilling without spending RentCast/GIS calls on ingest."""
    session = SessionLocal()
    try:
        already_done = {
            listing_id for (listing_id,) in
            session.query(ListingFeatures.listing_id)
            .filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
        }
        listings = session.query(Listing).filter(~Listing.id.in_(already_done)).all()
        listings = _excluding_property_types(listings)
        logger.info("computing features for %d listings (%d already done)", len(listings), len(already_done))
        compute_features_for_listings(session, listings)
        logger.info("done")
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
    subparsers.add_parser("compute-features", help="Run Stage 4 (feature vectors) standalone")

    args = parser.parse_args()
    if args.command == "run-weekly":
        run_weekly(dry_run=args.dry_run)
    elif args.command == "compute-features":
        compute_features()


if __name__ == "__main__":
    main()
