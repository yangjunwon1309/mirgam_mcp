from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform

from ..config import get_settings
from .store import FarmMapStore


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("farmmap-worker")
R = 6_378_137.0


async def crop_boundary(
    job: dict[str, object], store: FarmMapStore, min_zoom: int, max_zoom: int,
) -> None:
    params = json.loads(str(job["params_json"]))
    boundary_id = str(params["boundary_id"])
    boundary = store.boundary_for_crop(boundary_id)
    if not boundary:
        raise RuntimeError("경계 데이터를 찾지 못했습니다.")
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
    projected = transform(transformer.transform, shape(boundary["geojson"]))
    min_x, min_y, max_x, max_y = projected.bounds

    # Define one broad, fixed viewing area on the Z13 pixel grid. The map canvas
    # is roughly 1.3:1 and can be as large as 960x720 CSS pixels in the dashboard;
    # keep some room around it so Z13 shows the surrounding landscape. Higher
    # zooms share these exact ground bounds and are loaded as cached 256px tiles
    # on demand instead of materializing an enormous full-resolution mosaic.
    base_resolution = 2 * math.pi * R / (256 * (2**min_zoom))
    polygon_left = math.floor((min_x + math.pi * R) / base_resolution)
    polygon_right = math.ceil((max_x + math.pi * R) / base_resolution)
    polygon_top = math.floor((math.pi * R - max_y) / base_resolution)
    polygon_bottom = math.ceil((math.pi * R - min_y) / base_resolution)
    base_width = max(1024, math.ceil((polygon_right - polygon_left) * 1.25))
    base_height = max(768, math.ceil((polygon_bottom - polygon_top) * 1.25))
    center_pixel_x = (polygon_left + polygon_right) / 2
    center_pixel_y = (polygon_top + polygon_bottom) / 2
    world_pixels = 256 * 2**min_zoom
    base_pixel_left = max(0, min(world_pixels - base_width, math.floor(center_pixel_x - base_width / 2)))
    base_pixel_top = max(0, min(world_pixels - base_height, math.floor(center_pixel_y - base_height / 2)))
    base_pixel_right = base_pixel_left + base_width
    base_pixel_bottom = base_pixel_top + base_height
    if base_pixel_right <= base_pixel_left or base_pixel_bottom <= base_pixel_top:
        raise RuntimeError("농장 경계 크롭 범위를 계산하지 못했습니다.")
    ground_bounds = {
        "min_x": -math.pi * R + base_pixel_left * base_resolution,
        "max_x": -math.pi * R + base_pixel_right * base_resolution,
        "min_y": math.pi * R - base_pixel_bottom * base_resolution,
        "max_y": math.pi * R - base_pixel_top * base_resolution,
    }
    tile_pyramid: dict[str, Any] = {
        "min_zoom": min_zoom, "max_zoom": max_zoom, "coverage_zoom": min_zoom,
        "coverage_aligned": True, "coverage_mode": "cached_slippy_tiles_v2",
        "base_viewport_pixels": {"width": base_width, "height": base_height},
        "generation": str(job["id"]),
        "ground_bounds_3857": ground_bounds, "zooms": {},
    }
    for zoom in range(min_zoom, max_zoom + 1):
        scale = 2 ** (zoom - min_zoom)
        resolution = base_resolution / scale
        pixel_left = base_pixel_left * scale
        pixel_right = base_pixel_right * scale
        pixel_top = base_pixel_top * scale
        pixel_bottom = base_pixel_bottom * scale
        tile_min_x = max(0, math.floor(pixel_left / 256))
        tile_max_x = min(2**zoom - 1, math.ceil(pixel_right / 256) - 1)
        tile_min_y = max(0, math.floor(pixel_top / 256))
        tile_max_y = min(2**zoom - 1, math.ceil(pixel_bottom / 256) - 1)
        tile_pyramid["zooms"][str(zoom)] = {
            "min_x": tile_min_x, "max_x": tile_max_x, "min_y": tile_min_y, "max_y": tile_max_y,
            "pixel_left": pixel_left, "pixel_top": pixel_top,
            "pixel_right": pixel_right, "pixel_bottom": pixel_bottom,
            "width": pixel_right - pixel_left, "height": pixel_bottom - pixel_top,
            "resolution_m_per_pixel": resolution,
        }
    store.update_job_progress(str(job["id"]), 0.9)
    store.complete_crop(
        str(job["id"]), boundary_id, None,
        {"crs": "EPSG:3857", "tile_pyramid": tile_pyramid}, [],
    )


async def run() -> None:
    settings = get_settings()
    store = FarmMapStore(settings.sqlite_path, settings.data_root)
    store.initialize()
    store.requeue_interrupted_jobs()
    queued_legacy = store.queue_legacy_boundary_pyramids()
    logger.info("Farm map tile worker started; queued %d legacy map extents", queued_legacy)
    while True:
        job = store.claim_next_job()
        if job is None:
            await asyncio.sleep(1)
            continue
        try:
            await crop_boundary(
                job, store, settings.vworld_sat_min_z, settings.vworld_sat_max_z,
            )
        except Exception as exc:
            message = str(exc) if isinstance(exc, RuntimeError) else f"지도 범위 준비 실패 ({type(exc).__name__})"
            store.fail_job(str(job["id"]), message)
            logger.error("Farm map job failed (job_id=%s, error_type=%s)", job["id"], type(exc).__name__)


if __name__ == "__main__":
    asyncio.run(run())
