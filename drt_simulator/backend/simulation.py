"""Render에서 실행되는 공동 DRT 경유지 시뮬레이터."""

from time import sleep

from backend.models import RideStatus
from backend.repository import RideRepository


def run_demo_trip_simulation(
    repository: RideRepository,
    trip_id: str,
    travel_seconds: float,
    dwell_seconds: float,
) -> None:
    """각 승차·하차 지점을 순서대로 진행하며 호출 문서를 갱신한다."""

    trip = repository.claim_demo_trip_simulation(trip_id)
    if trip is None:
        return
    route_steps = list(trip.get("route_steps") or [])
    for index, step in enumerate(route_steps):
        repository.update_demo_trip_progress(trip_id, index, "EN_ROUTE")
        sleep(travel_seconds)
        repository.update_demo_trip_progress(trip_id, index, "ARRIVED")
        sleep(dwell_seconds)
        stop_type = step.get("type")
        next_status = RideStatus.PICKED_UP if stop_type == "PICKUP" else RideStatus.COMPLETED
        next_phase = "BOARDED" if stop_type == "PICKUP" else "DROPPED_OFF"
        repository.update_demo_trip_progress(
            trip_id,
            index,
            next_phase,
            request_id=str(step.get("request_id")),
            request_status=next_status,
        )
    repository.update_demo_trip_progress(trip_id, len(route_steps) - 1, "COMPLETED")
