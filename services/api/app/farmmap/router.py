from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse

from ..schemas import AuthenticatedUser
from .attribution import ATTRIBUTION
from .geometry import calculate_boundary, calculate_route
from .schemas import BoundaryCreate, FarmCreate, FarmUpdate, RouteCreate
from .store import FarmMapStore


def create_router(require_session: Callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["farm geography"])

    @router.get("/health")
    async def farmmap_health(request: Request, user: AuthenticatedUser = Depends(require_session)):
        del user
        settings = request.app.state.settings
        configured_key = settings.vworld_key.get_secret_value() if settings.vworld_key else ""
        return {"status": "ok", "vworld_configured": bool(configured_key and settings.vworld_domain),
                "calc_crs": settings.calc_crs, "satellite_min_zoom": settings.vworld_sat_min_z,
                "satellite_max_zoom": settings.vworld_sat_max_z,
                "attribution": ATTRIBUTION}

    @router.get("/vworld/geocode")
    async def geocode(
        request: Request, address: str = Query(min_length=1, max_length=500),
        search_type: str = Query("parcel", alias="type"),
        user: AuthenticatedUser = Depends(require_session),
    ):
        del user
        return await request.app.state.vworld.geocode(address, search_type)

    @router.get("/vworld/parcel")
    async def parcel(
        request: Request, lon: float = Query(ge=124, le=132), lat: float = Query(ge=33, le=39),
        user: AuthenticatedUser = Depends(require_session),
    ):
        del user
        return await request.app.state.vworld.parcel(lon, lat)

    @router.get("/tiles/{layer}/{z}/{x}/{y}")
    async def tile(
        layer: str, z: int, x: int, y: int, request: Request,
        user: AuthenticatedUser = Depends(require_session),
    ):
        del user
        content, media_type = await request.app.state.vworld.tile(layer, z, x, y)
        return Response(content, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})

    @router.get("/farms")
    async def list_farms(request: Request, user: AuthenticatedUser = Depends(require_session)):
        store: FarmMapStore = request.app.state.farmmap_store
        return [{**farm, "attribution": ATTRIBUTION} for farm in store.list_farms(user.account_id)]

    @router.post("/farms", status_code=201)
    async def create_farm(payload: FarmCreate, request: Request, user: AuthenticatedUser = Depends(require_session)):
        store: FarmMapStore = request.app.state.farmmap_store
        farm = store.create_farm(user.account_id, payload.name, payload.address_input, payload.pnu)
        return {**farm, "attribution": ATTRIBUTION}

    @router.patch("/farms/{farm_id}")
    async def update_farm(
        farm_id: str, payload: FarmUpdate, request: Request,
        user: AuthenticatedUser = Depends(require_session),
    ):
        farm = request.app.state.farmmap_store.update_farm(
            user.account_id, farm_id, payload.model_dump(exclude_unset=True)
        )
        if not farm:
            raise HTTPException(404, detail={"code": "FARM_NOT_FOUND", "message": "농장을 찾지 못했습니다."})
        return {**farm, "attribution": ATTRIBUTION}

    @router.get("/farms/{farm_id}")
    async def get_farm(farm_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        store: FarmMapStore = request.app.state.farmmap_store
        farm = store.get_farm(user.account_id, farm_id)
        if not farm:
            raise HTTPException(404, detail={"code": "FARM_NOT_FOUND", "message": "농장을 찾지 못했습니다."})
        return {**farm, "attribution": ATTRIBUTION}

    @router.get("/farms/{farm_id}/boundaries")
    async def list_boundaries(farm_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        store: FarmMapStore = request.app.state.farmmap_store
        boundaries = store.list_boundaries(user.account_id, farm_id)
        if boundaries is None:
            raise HTTPException(404, detail={"code": "FARM_NOT_FOUND", "message": "농장을 찾지 못했습니다."})
        return [{**boundary, "attribution": ATTRIBUTION} for boundary in boundaries]

    @router.post("/farms/{farm_id}/boundaries", status_code=201)
    async def create_boundary(
        farm_id: str, payload: BoundaryCreate, request: Request,
        user: AuthenticatedUser = Depends(require_session),
    ):
        measured = calculate_boundary(payload.coordinates, request.app.state.settings.calc_crs)
        store: FarmMapStore = request.app.state.farmmap_store
        result = store.create_boundary(
            user.account_id, farm_id, measured["geometry"], float(measured["area_m2"]),
            float(measured["perimeter_m"]), measured["edges"],
            payload.imagery_zoom or request.app.state.settings.vworld_sat_max_z,
        )
        if not result:
            raise HTTPException(404, detail={"code": "FARM_NOT_FOUND", "message": "농장을 찾지 못했습니다."})
        result["attribution"] = ATTRIBUTION
        result["calc_crs"] = request.app.state.settings.calc_crs
        return result

    @router.get("/farms/{farm_id}/routes")
    async def list_routes(farm_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        farm = request.app.state.farmmap_store.get_farm(user.account_id, farm_id)
        if not farm:
            raise HTTPException(404, detail={"code": "FARM_NOT_FOUND", "message": "농장을 찾지 못했습니다."})
        return [{**route, "attribution": ATTRIBUTION} for route in farm["routes"]]

    @router.post("/farms/{farm_id}/routes", status_code=201)
    async def create_route(
        farm_id: str, payload: RouteCreate, request: Request,
        user: AuthenticatedUser = Depends(require_session),
    ):
        measured = calculate_route(payload.coordinates, request.app.state.settings.calc_crs)
        route = request.app.state.farmmap_store.create_route(
            user.account_id, farm_id, payload.boundary_id, payload.label,
            measured["geometry"], float(measured["length_m"]),
        )
        if not route:
            raise HTTPException(404, detail={"code": "BOUNDARY_NOT_FOUND", "message": "농장 또는 경계를 찾지 못했습니다."})
        route["attribution"] = ATTRIBUTION
        route["calc_crs"] = request.app.state.settings.calc_crs
        return route

    @router.delete("/routes/{route_id}", status_code=204)
    async def delete_route(route_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        deleted = request.app.state.farmmap_store.delete_route(user.account_id, route_id)
        if not deleted:
            raise HTTPException(404, detail={"code": "ROUTE_NOT_FOUND", "message": "경로를 찾지 못했습니다."})
        return Response(status_code=204)

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        job = request.app.state.farmmap_store.get_job(user.account_id, job_id)
        if not job:
            raise HTTPException(404, detail={"code": "JOB_NOT_FOUND", "message": "작업을 찾지 못했습니다."})
        return job

    @router.get("/boundaries/{boundary_id}/imagery.json")
    async def imagery_metadata(boundary_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        boundary = request.app.state.farmmap_store.boundary_imagery(user.account_id, boundary_id)
        if not boundary:
            raise HTTPException(404, detail={"code": "BOUNDARY_NOT_FOUND", "message": "농장 경계를 찾지 못했습니다."})
        return {"boundary_id": boundary_id, "imagery": boundary["imagery"], "attribution": ATTRIBUTION}

    @router.get("/boundaries/{boundary_id}/imagery/{z}.jpg")
    async def boundary_zoom_image(
        boundary_id: str, z: int, request: Request,
        user: AuthenticatedUser = Depends(require_session),
    ):
        settings = request.app.state.settings
        if not settings.vworld_sat_min_z <= z <= settings.vworld_sat_max_z:
            raise HTTPException(404, detail={"code": "FARM_IMAGE_NOT_FOUND", "message": "해당 배율의 농장 지도를 찾지 못했습니다."})
        image_path = request.app.state.farmmap_store.boundary_zoom_image(user.account_id, boundary_id, z)
        if not image_path or not Path(image_path).is_file():
            raise HTTPException(404, detail={"code": "FARM_IMAGE_NOT_FOUND", "message": "해당 배율의 농장 지도를 찾지 못했습니다."})
        return FileResponse(
            image_path, media_type="image/jpeg",
            # HTTP header values are Latin-1; the Korean attribution text belongs
            # in the rendered map and JSON metadata, not in a response header.
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @router.get("/boundaries/{boundary_id}/tiles/{z}/{x}/{y}")
    async def boundary_tile(
        boundary_id: str, z: int, x: int, y: int, request: Request,
        user: AuthenticatedUser = Depends(require_session),
    ):
        settings = request.app.state.settings
        if not (settings.vworld_sat_min_z <= z <= settings.vworld_sat_max_z and 0 <= x < 2**z and 0 <= y < 2**z):
            raise HTTPException(404, detail={"code": "FARM_TILE_NOT_FOUND", "message": "저장된 농장 지도 타일을 찾지 못했습니다."})
        path = request.app.state.farmmap_store.boundary_tile(user.account_id, boundary_id, z, x, y)
        if not path or not Path(path).is_file():
            raise HTTPException(404, detail={"code": "FARM_TILE_NOT_FOUND", "message": "저장된 농장 지도 타일을 찾지 못했습니다."})
        return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @router.post("/boundaries/{boundary_id}/tiles/rebuild", status_code=202)
    async def rebuild_boundary_tiles(
        boundary_id: str, request: Request, force: bool = Query(False),
        user: AuthenticatedUser = Depends(require_session),
    ):
        boundary = request.app.state.farmmap_store.queue_boundary_tiles(user.account_id, boundary_id, force)
        if not boundary:
            raise HTTPException(404, detail={"code": "BOUNDARY_NOT_FOUND", "message": "농장 경계를 찾지 못했습니다."})
        boundary["attribution"] = ATTRIBUTION
        return boundary

    @router.get("/boundaries/{boundary_id}/imagery.png")
    async def boundary_imagery(boundary_id: str, request: Request, user: AuthenticatedUser = Depends(require_session)):
        boundary = request.app.state.farmmap_store.boundary_imagery(user.account_id, boundary_id)
        if not boundary:
            raise HTTPException(404, detail={"code": "BOUNDARY_NOT_FOUND", "message": "농장 경계를 찾지 못했습니다."})
        if not boundary["imagery"]["available"]:
            raise HTTPException(409, detail={"code": "IMAGERY_NOT_READY", "message": "위성영상 크롭 작업이 아직 완료되지 않았습니다."})
        image_path = request.app.state.settings.data_root / "imagery" / boundary_id / "crop_attr.png"
        if not image_path.is_file():
            raise HTTPException(404, detail={"code": "IMAGERY_MISSING", "message": "저장된 위성영상 파일을 찾지 못했습니다."})
        return FileResponse(image_path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    return router
