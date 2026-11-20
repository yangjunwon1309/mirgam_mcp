from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from .attribution import ATTRIBUTION
from .store import FarmMapStore


logger = logging.getLogger(__name__)
BASE = "https://api.vworld.kr"
LAYERS = {"Satellite": "jpeg", "Hybrid": "png", "Base": "png"}


class VWorldClient:
    def __init__(self, key: str | None, domain: str | None, store: FarmMapStore, data_root: Path, tile_ttl_days: int):
        self.key = key
        self.domain = domain
        self.store = store
        self.data_root = data_root
        self.tile_ttl = timedelta(days=max(tile_ttl_days, 1))
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(10.0))

    async def close(self) -> None:
        await self.http.aclose()

    def _require_credentials(self, include_domain: bool = False) -> None:
        if not self.key or (include_domain and not self.domain):
            raise HTTPException(503, detail={"code": "VWORLD_NOT_CONFIGURED", "message": "서버의 VWORLD_KEY 및 VWORLD_DOMAIN 환경변수를 설정해 주세요."})

    async def _get(self, url: str, params: dict[str, object], *, add_key: bool = True) -> httpx.Response:
        self._require_credentials(include_domain="domain" in params)
        params = {**params, **({"key": self.key} if add_key else {})}
        if "domain" in params:
            params["domain"] = self.domain
        for attempt in range(3):
            try:
                response = await self.http.get(url, params=params)
                if response.status_code >= 500 and attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                return response
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 2:
                    logger.warning("VWorld request failed (error_type=%s)", type(exc).__name__)
                    raise HTTPException(504, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 요청 시간이 초과되었거나 연결할 수 없습니다."}) from None
                await asyncio.sleep(0.5 * (2**attempt))
        raise HTTPException(504, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 요청에 실패했습니다."})

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise VWorldClient._upstream_error(response)
        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 응답을 읽을 수 없습니다."}) from None
        if not isinstance(body, dict):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 응답 형식이 예상과 다릅니다."})
        return body

    @staticmethod
    def _upstream_error(response: httpx.Response) -> HTTPException:
        detail = response.text[:300].upper() if response.text else ""
        if any(marker in detail for marker in ("INCORRECT_KEY", "INVALID_KEY", "INVALIDKEY", "KEY_ERROR", "DOMAIN")) or response.status_code in (401, 403):
            return HTTPException(502, detail={"code": "VWORLD_AUTH", "message": "VWorld 인증키 또는 등록 도메인을 확인해 주세요."})
        if response.status_code == 429:
            return HTTPException(429, detail={"code": "VWORLD_QUOTA", "message": "VWorld 요청 한도에 도달했습니다."})
        if response.status_code >= 500:
            return HTTPException(503, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 서비스를 일시적으로 사용할 수 없습니다."})
        return HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 요청이 거부되었습니다."})

    async def geocode(self, address: str, search_type: str = "parcel") -> dict[str, object]:
        self._require_credentials()
        if not address.strip():
            raise HTTPException(422, detail={"code": "ADDRESS_REQUIRED", "message": "주소를 입력해 주세요."})
        if search_type not in {"parcel", "road"}:
            raise HTTPException(422, detail={"code": "INVALID_ADDRESS_TYPE", "message": "주소 유형은 parcel 또는 road여야 합니다."})
        types = [search_type] if search_type == "road" else ["parcel", "road"]
        for current_type in types:
            count = self.store.record_geocode_call()
            if count >= 32_000 and count % 100 == 0:
                logger.warning("VWorld geocoder daily request count is at or above 80%% of the 40000 request quota")
            response = await self._get(
                f"{BASE}/req/address",
                {"service": "address", "request": "GetCoord", "version": "2.0", "crs": "EPSG:4326",
                 "type": current_type, "address": address, "format": "json"},
            )
            body = self._json(response)
            result = body.get("response") or {}
            if not isinstance(result, dict):
                raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 주소 응답 형식이 예상과 다릅니다."})
            status = str(result.get("status", "")).upper()
            if status == "OK":
                coordinate_result = result.get("result")
                point = coordinate_result.get("point") if isinstance(coordinate_result, dict) else None
                if not isinstance(point, dict):
                    raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 주소 응답에 좌표가 없습니다."})
                try:
                    lon, lat = float(point["x"]), float(point["y"])
                except (KeyError, TypeError, ValueError):
                    raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 주소 응답에 좌표가 없습니다."}) from None
                if not (124 <= lon <= 132 and 33 <= lat <= 39):
                    raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "주소 응답 좌표가 대한민국 범위를 벗어났습니다."})
                return {"lon": lon, "lat": lat, "type_used": current_type, "attribution": ATTRIBUTION}
            if status not in {"NOT_FOUND", "EMPTY"}:
                message = str(result.get("error") or result.get("message") or "").upper()
                if any(marker in message for marker in ("INCORRECT_KEY", "INVALID_KEY", "DOMAIN")):
                    raise HTTPException(502, detail={"code": "VWORLD_AUTH", "message": "VWorld 인증키 또는 등록 도메인을 확인해 주세요."})
                if any(marker in message for marker in ("QUOTA", "LIMIT_EXCEEDED", "TOO_MANY_REQUESTS")):
                    raise HTTPException(429, detail={"code": "VWORLD_QUOTA", "message": "VWorld 요청 한도에 도달했습니다."})
                logger.warning("VWorld geocoder rejected request (status=%s)", status or "unknown")
                raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 주소 검색에 실패했습니다."})
        raise HTTPException(404, detail={"code": "VWORLD_NOT_FOUND", "message": "주소를 찾지 못했습니다. 지번 또는 도로명 주소를 확인해 주세요."})

    async def parcel(self, lon: float, lat: float) -> dict[str, object]:
        self._require_credentials(include_domain=True)
        response = await self._get(
            f"{BASE}/req/data",
            {"service": "data", "request": "GetFeature", "data": "LP_PA_CBND_BUBUN",
             "geomFilter": f"POINT({lon} {lat})", "crs": "EPSG:4326", "format": "json", "size": 10,
             "domain": self.domain},
        )
        body = self._json(response)
        response_body = body.get("response")
        if not isinstance(response_body, dict):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 필지 응답 형식이 예상과 다릅니다."})
        result = response_body.get("result") or {}
        if not isinstance(result, dict):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 필지 응답 형식이 예상과 다릅니다."})
        feature_collection = result.get("featureCollection") or {}
        if not isinstance(feature_collection, dict):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 필지 응답 형식이 예상과 다릅니다."})
        features = feature_collection.get("features", [])
        if not isinstance(features, list):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 필지 응답 형식이 예상과 다릅니다."})
        if not features:
            raise HTTPException(404, detail={"code": "VWORLD_NOT_FOUND", "message": "해당 위치에서 필지 정보를 찾지 못했습니다."})
        feature = features[0]
        if not isinstance(feature, dict) or not isinstance(feature.get("geometry"), dict):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 필지 응답에 도형이 없습니다."})
        props = feature.get("properties") or {}
        if not isinstance(props, dict):
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld 필지 응답의 속성 형식이 예상과 다릅니다."})
        return {"type": "Feature", "geometry": feature.get("geometry"), "properties": props,
                "pnu": props.get("pnu"), "attribution": ATTRIBUTION}

    async def tile(self, layer: str, z: int, x: int, y: int) -> tuple[bytes, str]:
        if layer not in LAYERS:
            raise HTTPException(400, detail={"code": "INVALID_LAYER", "message": "허용 레이어는 Satellite, Hybrid, Base입니다."})
        if not (0 <= z <= 22) or not (0 <= x < 2**z) or not (0 <= y < 2**z):
            raise HTTPException(400, detail={"code": "INVALID_TILE", "message": "타일 좌표가 유효하지 않습니다."})
        self._require_credentials()
        extension = LAYERS[layer]
        cached = self.store.get_tile(layer, z, x, y)
        if cached:
            tile_path = Path(str(cached["path"]))
            fetched_at = datetime.fromisoformat(str(cached["fetched_at"]))
            if int(cached["status"]) == 200 and tile_path.is_file():
                if datetime.now(timezone.utc) - fetched_at.astimezone(timezone.utc) <= self.tile_ttl:
                    return tile_path.read_bytes(), f"image/{extension}"
                # Keep stale imagery available if the provider is temporarily offline.
                try:
                    data, media_type = await self._download_tile(layer, z, x, y, extension)
                    tile_path.write_bytes(data)
                    self.store.put_tile(layer, z, x, y, str(tile_path), 200)
                    return data, media_type
                except HTTPException:
                    return tile_path.read_bytes(), f"image/{extension}"
        data, media_type = await self._download_tile(layer, z, x, y, extension)
        tile_path = self.data_root / "tiles" / layer / str(z) / str(x) / f"{y}.{extension}"
        tile_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = tile_path.with_suffix(tile_path.suffix + ".tmp")
        temporary.write_bytes(data)
        temporary.replace(tile_path)
        self.store.put_tile(layer, z, x, y, str(tile_path), 200)
        return data, media_type

    async def _download_tile(self, layer: str, z: int, x: int, y: int, extension: str) -> tuple[bytes, str]:
        # VWorld's upstream WMTS path orders the tile coordinates as z/y/x.
        url = f"{BASE}/req/wmts/1.0.0/{quote(str(self.key or ''), safe='')}/{layer}/{z}/{y}/{x}.{extension}"
        response = await self._get(url, {}, add_key=False)
        if response.status_code >= 400:
            raise self._upstream_error(response)
        media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if not media_type.startswith("image/"):
            body = response.text[:300].upper()
            if any(marker in body for marker in ("INCORRECT_KEY", "INVALID_KEY", "DOMAIN")):
                raise HTTPException(502, detail={"code": "VWORLD_AUTH", "message": "VWorld 인증키 또는 등록 도메인을 확인해 주세요."})
            raise HTTPException(502, detail={"code": "VWORLD_UNAVAILABLE", "message": "VWorld가 지도 타일 대신 오류 응답을 보냈습니다."})
        return response.content, media_type
