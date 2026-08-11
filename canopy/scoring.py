"""Stage 3: canopy % cover + old-growth proxy scoring. Fully deterministic
per docs/CLAUDE.md -- no AI involved in this stage.

Parcel.geometry_geojson (written by canopy.enrich) is stored in the New
Hanover County native CRS (NC State Plane, ESRI:103122, US feet) -- that's
what nhc_gis.find_parcel_for_point returns when queried with outSR=103122.
"""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from canopy.clients.canopy_raster import canopy_pct_for_geometry
from canopy.db.models import Listing, Parcel, Score

logger = logging.getLogger(__name__)

PARCEL_GEOMETRY_CRS = "ESRI:103122"

# Old-growth proxy heuristic (documented limitation per ARCHITECTURE.md --
# no canonical "old growth" dataset exists). Combines parcel age and canopy
# density into a single 0-1 score: half weight on how old the structure is
# (capped at 100 years, since anything past that is "old" for this
# purpose), half weight on canopy density. Weights are tunable, not derived
# from any ground-truth data -- expect to retune after seeing real results.
OLD_GROWTH_AGE_CAP_YEARS = 100
OLD_GROWTH_AGE_WEIGHT = 0.5
OLD_GROWTH_CANOPY_WEIGHT = 0.5


def old_growth_proxy_score(year_built: int | None, canopy_pct: float | None) -> float | None:
    if year_built is None or canopy_pct is None:
        return None
    age_years = max(dt.date.today().year - year_built, 0)
    age_score = min(age_years / OLD_GROWTH_AGE_CAP_YEARS, 1.0)
    canopy_score = min(max(canopy_pct / 100.0, 0.0), 1.0)
    return OLD_GROWTH_AGE_WEIGHT * age_score + OLD_GROWTH_CANOPY_WEIGHT * canopy_score


def score_listings(session: Session, listings: list[Listing]) -> list[Score]:
    results: list[Score] = []

    for listing in listings:
        parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
        canopy_pct = None
        if parcel is not None and parcel.geometry_geojson is not None:
            canopy_pct = canopy_pct_for_geometry(parcel.geometry_geojson, PARCEL_GEOMETRY_CRS)

        score = session.query(Score).filter_by(listing_id=listing.id).one_or_none()
        if score is None:
            score = Score(listing_id=listing.id)
            session.add(score)

        score.canopy_pct = canopy_pct
        score.old_growth_proxy_score = old_growth_proxy_score(listing.year_built, canopy_pct)
        score.scored_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

        session.commit()  # per-listing, so a mid-run failure doesn't lose already-scored listings
        results.append(score)
        logger.info(
            "scored %s: canopy_pct=%s old_growth_proxy=%s",
            listing.id, score.canopy_pct, score.old_growth_proxy_score,
        )

    return results
