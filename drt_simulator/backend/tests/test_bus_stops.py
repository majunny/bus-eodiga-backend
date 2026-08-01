"""울산 정류소 CSV 검색 테스트."""

from backend.bus_stops import get_bus_stop_service


def test_only_ulsan_stops_are_loaded() -> None:
    service = get_bus_stop_service()
    assert service.count == 3_616
    assert all(stop.district.startswith("울산광역시") for stop in service.search("", 100))


def test_search_finds_named_stops() -> None:
    results = get_bus_stop_service().search("태화강역", 20)
    assert results
    assert all("태화강역" in stop.name for stop in results)
    assert all(stop.stop_id for stop in results)


def test_nearby_returns_distance_order() -> None:
    results = get_bus_stop_service().nearby(35.53937, 129.35194, radius_m=1_000, limit=20)
    assert results
    distances = [stop.distance_m for stop in results]
    assert distances == sorted(distances)
    assert distances[0] == 0.0
