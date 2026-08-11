"""Stage 2: enrich each new/changed listing with New Hanover County GIS data
(parcel geometry, adjacency, flood zone, wetland overlay) and persist it."""

import datetime as dt
import logging

from sqlalchemy.orm import Session

from canopy.clients.nhc_gis import enrich_parcel
from canopy.db.models import Listing, Parcel

logger = logging.getLogger(__name__)


def enrich_listings(session: Session, listings: list[Listing]) -> list[Parcel]:
    results: list[Parcel] = []

    for listing in listings:
        gis_data = enrich_parcel(listing.latitude, listing.longitude)

        parcel = session.query(Parcel).filter_by(listing_id=listing.id).one_or_none()
        if parcel is None:
            parcel = Parcel(listing_id=listing.id)
            session.add(parcel)

        parcel.parcel_id = gis_data["parcel_id"]
        parcel.geometry_geojson = gis_data["geometry_geojson"]
        parcel.adjacent_water = gis_data["adjacent_water"]
        parcel.adjacent_park_or_conservation = gis_data["adjacent_park_or_conservation"]
        parcel.adjacent_county_or_city_owned = gis_data["adjacent_county_or_city_owned"]
        parcel.flood_zone = gis_data["flood_zone"]
        parcel.wetland_overlay = gis_data["wetland_overlay"]
        parcel.raw_gis = gis_data["raw_gis"]
        parcel.enriched_at = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)

        session.commit()  # per-listing, so a mid-run failure doesn't lose already-enriched parcels
        results.append(parcel)
        logger.info(
            "enriched %s: parcel=%s water=%s park/cons=%s county=%s flood=%s wetland=%s",
            listing.id, parcel.parcel_id, parcel.adjacent_water,
            parcel.adjacent_park_or_conservation, parcel.adjacent_county_or_city_owned,
            parcel.flood_zone, parcel.wetland_overlay,
        )

    return results
