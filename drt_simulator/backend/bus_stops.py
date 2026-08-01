"""울산광역시 버스 정류소 CSV 검색 서비스."""

import csv
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from backend.models import BusStopResponse


DEFAULT_DATA_PATH = Path(__file__).with_name("data") / "ulsan_bus_stops_20260522.csv"


class BusStopService:
    """정류소 원본을 메모리에 한 번 적재해 이름·거리 검색을 수행한다."""

    def __init__(self, data_path: Path = DEFAULT_DATA_PATH) -> None:
        self._stops = self._load(data_path)

    @staticmethod
    def _load(data_path: Path) -> tuple[BusStopResponse, ...]:
        stops: list[BusStopResponse] = []
        with data_path.open(encoding="utf-8-sig", newline="") as source:
            for row_number, row in enumerate(csv.DictReader(source), start=2):
                district = row["권역"].strip()
                if not district.startswith("울산광역시"):
                    continue
                source_id = row["서비스아이디"].strip()
                stop_id = source_id if source_id and source_id != "0" else f"local-{row_number:04d}"
                stops.append(
                    BusStopResponse(
                        stop_id=stop_id,
                        name=row["정류장명"].strip(),
                        latitude=float(row["위도"]),
                        longitude=float(row["경도"]),
                        district=district,
                    )
                )
        return tuple(stops)

    @property
    def count(self) -> int:
        return len(self._stops)

    def search(self, query: str, limit: int) -> list[BusStopResponse]:
        """이름에 검색어가 포함된 정류소를 반환한다."""

        normalized = query.strip().casefold()
        matches = (stop for stop in self._stops if normalized in stop.name.casefold())
        return sorted(matches, key=lambda stop: (stop.name, stop.stop_id))[:limit]

    def nearby(
        self,
        latitude: float,
        longitude: float,
        radius_m: float,
        limit: int,
    ) -> list[BusStopResponse]:
        """입력 좌표에서 가까운 순서로 반경 내 정류소를 반환한다."""

        matches: list[BusStopResponse] = []
        for stop in self._stops:
            distance = _haversine_m(latitude, longitude, stop.latitude, stop.longitude)
            if distance <= radius_m:
                matches.append(stop.model_copy(update={"distance_m": round(distance, 1)}))
        return sorted(matches, key=lambda stop: (stop.distance_m or 0.0, stop.stop_id))[:limit]


def _haversine_m(start_lat: float, start_lon: float, end_lat: float, end_lon: float) -> float:
    """두 WGS84 좌표 사이의 대권 거리를 미터로 계산한다."""

    earth_radius_m = 6_371_000.0
    lat_delta = radians(end_lat - start_lat)
    lon_delta = radians(end_lon - start_lon)
    start_latitude = radians(start_lat)
    end_latitude = radians(end_lat)
    value = sin(lat_delta / 2) ** 2 + cos(start_latitude) * cos(end_latitude) * sin(lon_delta / 2) ** 2
    return 2 * earth_radius_m * asin(sqrt(value))


@lru_cache(maxsize=1)
def get_bus_stop_service() -> BusStopService:
    """프로세스 전체에서 정류소 데이터 한 사본을 재사용한다."""

    return BusStopService()
