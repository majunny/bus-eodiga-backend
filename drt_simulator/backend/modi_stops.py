"""MODI 키오스크·모형 차량이 공통으로 사용하는 여섯 정류장."""

from __future__ import annotations

from backend.models import Coordinate, PlacePayload


MODI_BUS_STOPS = [
    {"name": "동부아파트입구", "latitude": 35.52742029, "longitude": 129.3225519, "stop_id": "31208"},
    {"name": "수암시장앞", "latitude": 35.52792702, "longitude": 129.3207326, "stop_id": "31205"},
    {"name": "공업탑", "latitude": 35.53301001, "longitude": 129.3097744, "stop_id": "40404"},
    {"name": "달동현대아파트앞", "latitude": 35.53630572, "longitude": 129.3237411, "stop_id": "40411"},
    {"name": "강남초등학교", "latitude": 35.5358198, "longitude": 129.3205483, "stop_id": "40410"},
    {"name": "롯데마트", "latitude": 35.5336866, "longitude": 129.3167411, "stop_id": "64201"},
]

MODI_DEPOT_STOP_ID = "31208"
MODI_STOPS_BY_ID = {stop["stop_id"]: stop for stop in MODI_BUS_STOPS}


def modi_place(stop_id: str) -> PlacePayload:
    """정류장 ID를 검증하고 API 장소 모델로 변환한다."""

    stop = MODI_STOPS_BY_ID.get(stop_id)
    if stop is None:
        raise KeyError(stop_id)
    return PlacePayload(
        place_id=stop["stop_id"],
        name=stop["name"],
        location=Coordinate(latitude=stop["latitude"], longitude=stop["longitude"]),
    )
