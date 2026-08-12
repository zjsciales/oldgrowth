import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from canopy.clients.canopy_raster import (
    RASTER_CRS,
    canopy_pct_for_geometry,
    neighborhood_canopy_buffer_pct,
)


@pytest.fixture()
def fake_raster(tmp_path, monkeypatch):
    path = tmp_path / "fake_canopy.tif"
    data = np.full((10, 10), 255, dtype="uint8")  # background
    data[2:8, 2:8] = 40  # a 6x6 block of 40% canopy
    data[4, 4] = 254  # a stray water pixel inside the block

    transform = from_origin(1630000, 1380000, 30, 30)  # 30m pixels, EPSG:5070-ish
    with rasterio.open(
        path, "w", driver="GTiff", height=10, width=10, count=1,
        dtype="uint8", crs=RASTER_CRS, transform=transform,
    ) as dst:
        dst.write(data, 1)

    monkeypatch.setattr("canopy.clients.canopy_raster.ensure_canopy_raster", lambda: path)
    return path


def test_canopy_pct_for_geometry_averages_valid_pixels(fake_raster):
    # A small polygon fully inside the 40%-canopy block, in the raster's own CRS.
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [1630090, 1379910], [1630150, 1379910],
            [1630150, 1379850], [1630090, 1379850], [1630090, 1379910],
        ]],
    }

    pct = canopy_pct_for_geometry(geom, RASTER_CRS)

    assert pct == pytest.approx(40.0)


def test_canopy_pct_for_geometry_returns_none_outside_raster(fake_raster):
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [0, 0], [10, 0], [10, 10], [0, 10], [0, 0],
        ]],
    }

    assert canopy_pct_for_geometry(geom, RASTER_CRS) is None


def test_neighborhood_canopy_buffer_pct_reaches_further_than_the_parcel(fake_raster):
    # exactly one background pixel (col 1, row 3), immediately west of the
    # 40%-canopy block (which starts at col 2) -- full pixel bounds so its
    # center is unambiguously inside the polygon under rasterio's default
    # center-point pixel inclusion rule
    geom = {
        "type": "Polygon",
        "coordinates": [[
            [1630030, 1379910], [1630060, 1379910],
            [1630060, 1379880], [1630030, 1379880], [1630030, 1379910],
        ]],
    }

    # unbuffered: entirely background (255, excluded) -> no valid pixels
    assert neighborhood_canopy_buffer_pct(geom, RASTER_CRS, buffer_m=0) is None
    # buffered far enough to reach into the 40%-canopy block
    assert neighborhood_canopy_buffer_pct(geom, RASTER_CRS, buffer_m=60) == pytest.approx(40.0)
