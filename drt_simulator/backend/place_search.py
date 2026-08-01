"""울산 영역의 OpenStreetMap 장소 이름 검색 서비스."""

from threading import Lock
from time import monotonic
from typing import Protocol

import httpx

from backend.models import PlaceSearchResponse


class PlaceSearchError(RuntimeError):
    """외부 장소 검색 서비스가 정상 응답을 제공하지 못한 경우."""


class PlaceSearchService(Protocol):
    """FastAPI에서 주입할 수 있는 장소 검색 계약."""

    def search(self, query: str, limit: int) -> list[PlaceSearchResponse]:
        """울산 경계 안에서 이름이 일치하는 장소를 반환한다."""


class NominatimPlaceSearchService:
    """Nominatim 공개 검색 API를 울산 범위로 제한해 사용한다."""

    ULSAN_VIEWBOX = "129.00,35.80,129.50,35.30"

    def __init__(self, base_url: str, timeout_seconds: float = 10.0, cache_seconds: float = 300.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.cache_seconds = cache_seconds
        self._cache: dict[tuple[str, int], tuple[float, list[PlaceSearchResponse]]] = {}
        self._cache_lock = Lock()

    def search(self, query: str, limit: int) -> list[PlaceSearchResponse]:
        normalized_query = " ".join(query.strip().split())
        if len(normalized_query) < 2:
            return []

        cache_key = (normalized_query.casefold(), limit)
        now = monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached and now - cached[0] < self.cache_seconds:
                return cached[1]

        try:
            response = httpx.get(
                f"{self.base_url}/search",
                params={
                    "q": normalized_query,
                    "format": "jsonv2",
                    "addressdetails": 1,
                    "limit": limit,
                    "viewbox": self.ULSAN_VIEWBOX,
                    "bounded": 1,
                    "countrycodes": "kr",
                    "accept-language": "ko",
                },
                headers={"User-Agent": "BUS-eodiga-hackathon/1.0"},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise PlaceSearchError("울산 장소 검색 서버에 연결하지 못했습니다.") from error

        if not isinstance(payload, list):
            raise PlaceSearchError("장소 검색 서버의 응답 형식이 올바르지 않습니다.")

        results: list[PlaceSearchResponse] = []
        for item in payload:
            try:
                display_name = str(item["display_name"])
                name = str(item.get("name") or display_name.split(",", maxsplit=1)[0]).strip()
                osm_type = str(item.get("osm_type") or "place")
                osm_id = str(item.get("osm_id") or item["place_id"])
                results.append(
                    PlaceSearchResponse(
                        place_id=f"osm-{osm_type}-{osm_id}",
                        name=name,
                        address=display_name,
                        latitude=float(item["lat"]),
                        longitude=float(item["lon"]),
                        category=str(item.get("category") or item.get("type") or "PLACE").upper(),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        with self._cache_lock:
            self._cache[cache_key] = (now, results)
        return results
