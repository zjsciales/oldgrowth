"""CLI entrypoints. Usage: python -m canopy.cli <command>"""

import argparse
import logging

from canopy.db.models import Listing, ListingFeatures, Parcel, Rater
from canopy.db.session import SessionLocal
from canopy.digest import send_digest
from canopy.email_ingest import ingest_from_email
from canopy.enrich import enrich_listings
from canopy.features import FEATURE_SET_VERSION, compute_features_for_listings
from canopy.ingest import ingest_all_zips
from canopy.model import compute_digest_slots, fit_model
from canopy.model import score_listings as score_preferences
from canopy.rating import is_hard_excluded
from canopy.rentcast_backfill import backfill_from_rentcast
from canopy.scoring import score_listings as score_canopy

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _excluding_hard_no(listings: list[Listing]) -> list[Listing]:
    """Listings that are never candidates at all (see
    canopy.rating.is_hard_excluded) skip every downstream stage -- GIS
    enrichment, canopy/raster scoring, feature computation, and (most
    importantly for cost) the lazy vision pass, which only ever runs on
    listings that reach the rating UI as candidates. Still
    ingested/stored (cheap, keeps market visibility), just never
    processed further."""
    return [listing for listing in listings if not is_hard_excluded(listing.property_type, listing.formatted_address)]


def _unenriched_backlog(session) -> list[Listing]:
    """Listings that were ingested but never finished GIS enrichment --
    e.g. a prior run crashed mid-Stage-2. `changed` from the ingest step
    won't reliably catch these on the next run (it's keyed on
    status/price/last_seen_date, not on pipeline completeness), so a
    crash here could otherwise leave a listing stuck forever."""
    enriched_ids = {
        listing_id for (listing_id,) in session.query(Parcel.listing_id).filter(Parcel.enriched_at.isnot(None))
    }
    backlog = session.query(Listing).filter(~Listing.id.in_(enriched_ids)).all()
    return _excluding_hard_no(backlog)


def _unfeatured_backlog(session) -> list[Listing]:
    """Same idea as _unenriched_backlog, one stage later: listings that
    were enriched/scored but never got a feature vector computed for the
    current FEATURE_SET_VERSION -- e.g. a crash mid-Stage-4."""
    featured_ids = {
        listing_id for (listing_id,) in
        session.query(ListingFeatures.listing_id).filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
    }
    backlog = session.query(Listing).filter(~Listing.id.in_(featured_ids)).all()
    return _excluding_hard_no(backlog)


def run_pipeline(session, ingest_fn) -> bool:
    """Stages 1-5: ingest (via a swappable ingest_fn), GIS enrichment,
    canopy scoring, feature vectors, per-rater preference model refit. No
    digest send -- that's run_digest's job, on its own weekly schedule,
    independent of how often this runs. Returns True if anything actually
    ran (used by run_daily to decide whether to log a no-op)."""
    logger.info("=== Stage 1: ingest ===")
    changed = ingest_fn(session)
    logger.info("%d new/changed listings", len(changed))

    backfilled = backfill_from_rentcast(session, changed)
    if backfilled:
        logger.info("%d listings collated with matching RentCast data", len(backfilled))
    changed = list({listing.id: listing for listing in [*changed, *backfilled]}.values())

    changed = _excluding_hard_no(changed)

    enrich_backlog = _unenriched_backlog(session)
    # checked upfront, before any stage runs -- a listing stuck only at
    # Stage 4 (already enriched, never featured) has nothing in `changed`
    # or `enrich_backlog` to keep it from being missed by the early-exit
    # check below
    feature_backlog = _unfeatured_backlog(session)

    if not changed and not enrich_backlog and not feature_backlog:
        logger.info("nothing new, exiting")
        return False

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
            "expected exactly 2 raters for joint scoring, found %d -- skipping model refit",
            len(raters),
        )
        return True
    rater_a, rater_b = raters[0].id, raters[1].id

    logger.info("=== Stage 5: refit preference models (%s, %s) ===", rater_a, rater_b)
    for rater_id in (rater_a, rater_b):
        model_run = fit_model(session, rater_id)
        score_preferences(session, model_run)
        logger.info("%s: n_pairs=%d holdout_accuracy=%s", rater_id, model_run.n_pairs, model_run.holdout_accuracy)

    return True


def run_daily() -> None:
    """Stages 1-5, email-sourced. New Railway Cron Job, daily -- replaces
    the old weekly ingest cadence now that RentCast's call budget is no
    longer a constraint (see canopy/config.py)."""
    session = SessionLocal()
    try:
        run_pipeline(session, ingest_fn=ingest_from_email)
    finally:
        session.close()


def run_digest(dry_run: bool = False) -> None:
    """Stage 6 only: reads whatever's already accumulated (raters, latest
    model runs) and sends the digest. Stays on its own weekly schedule,
    independent of run_daily."""
    session = SessionLocal()
    try:
        raters = session.query(Rater).order_by(Rater.id).all()
        if len(raters) != 2:
            logger.warning("expected exactly 2 raters for a digest, found %d -- skipping", len(raters))
            return
        rater_a, rater_b = raters[0].id, raters[1].id

        logger.info("=== Stage 6: digest ===")
        plan = compute_digest_slots(session, rater_a, rater_b)
        html = send_digest(session, plan, dry_run=dry_run)
        if dry_run:
            logger.info("dry-run digest HTML:\n%s", html)
    finally:
        session.close()


def compute_features() -> None:
    """Standalone Stage 4 (features) runner, independent of run_daily --
    handy for backfilling without re-running ingest/GIS/canopy scoring."""
    session = SessionLocal()
    try:
        already_done = {
            listing_id for (listing_id,) in
            session.query(ListingFeatures.listing_id)
            .filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
        }
        listings = session.query(Listing).filter(~Listing.id.in_(already_done)).all()
        listings = _excluding_hard_no(listings)
        logger.info("computing features for %d listings (%d already done)", len(listings), len(already_done))
        compute_features_for_listings(session, listings)
        logger.info("done")
    finally:
        session.close()


def run_rentcast_weekly() -> None:
    """RentCast refresh, every ~5 days -- restored as a background-only
    feed after RentCast's full retirement as the primary listings source
    (see docs/ARCHITECTURE.md's Appendix). RentCast-sourced rows still
    never enter the rating queue (canopy.rating.excluded_listing_ids) and
    never get GIS enrichment/canopy scoring/vision -- only Zillow-sourced
    listings need those. This job's only purpose is to keep
    canopy/rentcast_backfill.py's matching pool from going stale (see that
    module's docstring: the original 4/19 match rate was mostly a
    staleness artifact from a one-time historical pull). New Railway Cron
    Job, every ~5 days (6 zips x 1 call each x ~6 runs/month =~ 36 calls,
    comfortably under RentCast's 50-call/month free tier
    (RENTCAST_MONTHLY_CALL_BUDGET) -- daily or every-72-hours would blow
    past it)."""
    session = SessionLocal()
    try:
        logger.info("=== RentCast refresh: ingest ===")
        changed = ingest_all_zips(session)
        logger.info("%d new/changed RentCast listings", len(changed))

        logger.info("=== RentCast refresh: collate against Zillow listings ===")
        backfilled = backfill_from_rentcast(session)
        logger.info("%d Zillow listings collated with matching RentCast data", len(backfilled))
        if backfilled:
            compute_features_for_listings(session, backfilled)
    finally:
        session.close()


def backfill_rentcast() -> None:
    """Retroactive one-off: collate every already-ingested Zillow listing
    against RentCast's historical rows (run_pipeline only does this for
    newly-changed listings each day; this covers everything ingested
    before this feature existed, or a matching RentCast row that wasn't
    findable before an address-matching improvement). Recomputes feature
    vectors for anything that actually changed, since backfilled fields
    (lot size, year built, market history) feed the feature vector."""
    session = SessionLocal()
    try:
        changed = backfill_from_rentcast(session)
        logger.info("%d listings collated with matching RentCast data", len(changed))
        if changed:
            logger.info("recomputing feature vectors for backfilled listings")
            compute_features_for_listings(session, changed)
        logger.info("done")
    finally:
        session.close()


def backfill_parcel_geometry() -> None:
    """One-off: recompute feature vectors for Zillow-sourced listings that
    already have a ListingFeatures row but predate real parcel-outline/
    road-edge geometry (extra["parcel_outline"] missing) -- i.e. every
    listing ingested before that shipped. Scoped to source='zillow_email'
    only: RentCast rows never surface in the rating UI (canopy.rating.
    excluded_listing_ids), so there's no reason to spend a live GIS call
    refreshing their plate data. compute_boundary_features is already a
    live call on every feature computation (not cached at Stage 2), so
    this is just a normal Stage 4 rerun, scoped to what's actually stale."""
    session = SessionLocal()
    try:
        rows = (
            session.query(ListingFeatures)
            .filter(ListingFeatures.feature_set_version == FEATURE_SET_VERSION)
            .all()
        )
        stale_ids = {row.listing_id for row in rows if not (row.extra or {}).get("parcel_outline")}
        listings = (
            session.query(Listing)
            .filter(Listing.id.in_(stale_ids), Listing.source == "zillow_email")
            .all()
        )
        logger.info("recomputing features for %d listings missing real parcel geometry", len(listings))
        compute_features_for_listings(session, listings)
        logger.info("done")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="canopy")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("run-daily", help="Run Stages 1-5: ingest, enrich, score, feature, refit")
    digest = subparsers.add_parser("run-digest", help="Run Stage 6: send the weekly digest")
    digest.add_argument(
        "--dry-run", action="store_true",
        help="Compute the digest but skip sending the email (logs the digest instead)",
    )
    subparsers.add_parser("compute-features", help="Run Stage 4 (feature vectors) standalone")
    subparsers.add_parser(
        "run-rentcast", help="Weekly background RentCast refresh + collation (no rating candidates)"
    )
    subparsers.add_parser(
        "backfill-rentcast",
        help="Collate all Zillow listings against existing RentCast rows by address, without polling RentCast",
    )
    subparsers.add_parser(
        "backfill-parcel-geometry",
        help="Recompute features for Zillow listings missing real parcel outline/road-edge geometry",
    )

    args = parser.parse_args()
    if args.command == "run-daily":
        run_daily()
    elif args.command == "run-digest":
        run_digest(dry_run=args.dry_run)
    elif args.command == "compute-features":
        compute_features()
    elif args.command == "run-rentcast":
        run_rentcast_weekly()
    elif args.command == "backfill-rentcast":
        backfill_rentcast()
    elif args.command == "backfill-parcel-geometry":
        backfill_parcel_geometry()


if __name__ == "__main__":
    main()
