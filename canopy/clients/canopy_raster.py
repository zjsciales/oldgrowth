"""NLCD Tree Canopy Cover raster client (MRLC WCS).

New Hanover County does not host its own canopy layer -- confirmed by
enumerating every service under https://gis.nhcgov.com/server/rest/services
during Stage 2 development. This falls back to MRLC's NLCD Tree Canopy
Cover product (`nlcd_tcc_conus_2021_v2021-4`), fetched once for the whole
county via WCS GetCoverage and cached locally, then queried per-parcel with
`rasterstats` zonal stats. Deterministic -- no AI involved.

Important: MRLC's WMS `GetMap` returns a *styled* RGB-palette PNG-in-TIFF
that cannot be used for percentage math (verified during development). WCS
`GetCoverage` returns the real single-band pixel values (0-100 = % canopy,
254 = open water, 255 = background/no data) and is what this client uses.
"""

import os
from pathlib import Path

import numpy as np
import rasterio
import rasterio.mask
import requests
from rasterio.warp import transform_geom

WCS_URL = "https://www.mrlc.gov/geoserver/mrlc_download/wcs"
COVERAGE_ID = "mrlc_download__nlcd_tcc_conus_2021_v2021-4"
RASTER_CRS = "EPSG:5070"

# New Hanover County + surrounding buffer (covers mainland Wilmington plus
# Carolina/Kure Beach), in EPSG:5070 meters. Computed from a WGS84 bbox of
# roughly lon -78.15..-77.75, lat 33.95..34.35 via rasterio.warp.transform_bounds.
NHC_BBOX_5070 = (1619822.9, 1362748.9, 1664212.8, 1413567.5)

CACHE_PATH = Path(os.environ.get("CANOPY_RASTER_CACHE", "data/canopy_new_hanover.tif"))

NODATA_VALUES = (254, 255)


class CanopyRasterError(RuntimeError):
    pass


def ensure_canopy_raster(force: bool = False) -> Path:
    """Download (once) and cache the county-wide canopy raster."""
    if CACHE_PATH.exists() and not force:
        return CACHE_PATH

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    minx, miny, maxx, maxy = NHC_BBOX_5070
    resp = requests.get(
        WCS_URL,
        params={
            "SERVICE": "WCS",
            "VERSION": "2.0.1",
            "REQUEST": "GetCoverage",
            "coverageId": COVERAGE_ID,
            "subset": [f"X({minx},{maxx})", f"Y({miny},{maxy})"],
            "format": "image/geotiff",
        },
        timeout=120,
    )
    if resp.status_code != 200 or resp.headers.get("content-type") != "image/geotiff":
        raise CanopyRasterError(
            f"MRLC WCS request failed ({resp.status_code}, "
            f"content-type={resp.headers.get('content-type')}): {resp.text[:500]}"
        )

    CACHE_PATH.write_bytes(resp.content)
    return CACHE_PATH


def canopy_pct_for_geometry(geojson_geometry: dict, source_crs: str) -> float | None:
    """Mean canopy % cover for a parcel polygon (given in any CRS -- it's
    reprojected to match the raster). Returns None if the parcel doesn't
    overlap any valid (non-water, non-background) raster pixels."""
    raster_path = ensure_canopy_raster()
    reprojected = transform_geom(source_crs, RASTER_CRS, geojson_geometry)

    with rasterio.open(raster_path) as src:
        try:
            clipped, _ = rasterio.mask.mask(src, [reprojected], crop=True)
        except ValueError:
            # geometry doesn't overlap the raster extent at all
            return None

    values = clipped[0]
    valid = values[(values >= 0) & (values <= 100)]
    if valid.size == 0:
        return None
    return float(np.mean(valid))
