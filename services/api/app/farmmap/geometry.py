from __future__ import annotations

import math

from fastapi import HTTPException
from pyproj import Transformer
from shapely.geometry import LineString, Polygon, mapping
from shapely.geometry.polygon import orient
from shapely.ops import transform


def _projector(calc_crs: str) -> Transformer:
    try:
        return Transformer.from_crs("EPSG:4326", calc_crs, always_xy=True)
    except Exception:
        raise HTTPException(500, detail={"code": "INVALID_CALC_CRS", "message": "CALC_CRS 설정을 확인해 주세요."}) from None


def _validate_coords(coordinates: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for lon, lat in coordinates:
        if not math.isfinite(lon) or not math.isfinite(lat) or not (124 <= lon <= 132 and 33 <= lat <= 39):
            raise HTTPException(422, detail={"code": "COORDINATE_OUT_OF_RANGE", "message": "좌표는 대한민국 범위 안의 [경도, 위도]여야 합니다."})
        point = (float(lon), float(lat))
        if not result or point != result[-1]:
            result.append(point)
    return result


def calculate_boundary(coordinates: list[tuple[float, float]], calc_crs: str) -> dict[str, object]:
    points = _validate_coords(coordinates)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    if len(points) < 3:
        raise HTTPException(422, detail={"code": "BOUNDARY_TOO_SMALL", "message": "경계 꼭짓점이 3개 이상 필요합니다."})
    transformer = _projector(calc_crs)
    projected = [transformer.transform(lon, lat) for lon, lat in points]
    cleaned: list[tuple[float, float]] = []
    cleaned_projected: list[tuple[float, float]] = []
    for geo, metric in zip(points, projected):
        if not cleaned_projected or math.dist(metric, cleaned_projected[-1]) >= 0.05:
            cleaned.append(geo)
            cleaned_projected.append(metric)
    if len(cleaned_projected) > 2 and math.dist(cleaned_projected[0], cleaned_projected[-1]) < 0.05:
        cleaned.pop()
        cleaned_projected.pop()
    if len(cleaned) < 3:
        raise HTTPException(422, detail={"code": "BOUNDARY_TOO_SMALL", "message": "서로 다른 경계 꼭짓점이 3개 이상 필요합니다."})
    polygon = Polygon(cleaned)
    if not polygon.is_valid:
        raise HTTPException(422, detail={"code": "INVALID_BOUNDARY", "message": "경계가 자기 교차합니다. 꼭짓점 순서를 확인해 주세요."})
    polygon = orient(polygon, sign=1.0)
    metric_polygon = transform(transformer.transform, polygon)
    if metric_polygon.area <= 1:
        raise HTTPException(422, detail={"code": "BOUNDARY_TOO_SMALL", "message": "경계 면적은 1m²보다 커야 합니다."})
    ring = list(polygon.exterior.coords)
    metric_ring = [transformer.transform(lon, lat) for lon, lat in ring]
    edges = []
    perimeter = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = metric_ring[index]
        x2, y2 = metric_ring[index + 1]
        length = math.hypot(x2 - x1, y2 - y1)
        perimeter += length
        azimuth = (math.degrees(math.atan2(x2 - x1, y2 - y1)) + 360) % 360
        edges.append({"from": index, "to": (index + 1) % (len(ring) - 1), "length_m": round(length, 3), "azimuth_deg": round(azimuth, 2)})
    return {"geometry": mapping(polygon), "area_m2": round(metric_polygon.area, 3),
            "perimeter_m": round(perimeter, 3), "edges": edges}


def calculate_route(coordinates: list[tuple[float, float]], calc_crs: str) -> dict[str, object]:
    points = _validate_coords(coordinates)
    if len(points) < 2:
        raise HTTPException(422, detail={"code": "ROUTE_TOO_SHORT", "message": "경로는 꼭짓점이 2개 이상 필요합니다."})
    transformer = _projector(calc_crs)
    cleaned = [points[0]]
    metric = [transformer.transform(*points[0])]
    for point in points[1:]:
        projected = transformer.transform(*point)
        if math.dist(projected, metric[-1]) >= 0.05:
            cleaned.append(point)
            metric.append(projected)
    if len(cleaned) < 2:
        raise HTTPException(422, detail={"code": "ROUTE_TOO_SHORT", "message": "서로 다른 경로 꼭짓점이 2개 이상 필요합니다."})
    line = LineString(cleaned)
    metric_line = transform(transformer.transform, line)
    return {"geometry": mapping(line), "length_m": round(metric_line.length, 3)}
