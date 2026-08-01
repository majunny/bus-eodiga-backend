"""Validated storage and lifecycle operations for passenger requests."""

from collections import defaultdict
from typing import DefaultDict, Dict, List

from models import PassengerRequest, RequestStatus


class RequestManager:
    """Maintain unique requests and enforce legal state transitions."""

    _TRANSITIONS = {
        RequestStatus.WAITING: {RequestStatus.ASSIGNED, RequestStatus.CANCELLED},
        RequestStatus.ASSIGNED: {RequestStatus.PICKED_UP, RequestStatus.WAITING,
                                 RequestStatus.CANCELLED},
        RequestStatus.PICKED_UP: {RequestStatus.COMPLETED},
        RequestStatus.COMPLETED: set(),
        RequestStatus.CANCELLED: set(),
    }

    def __init__(self) -> None:
        """Create an empty request registry."""

        self._requests: Dict[str, PassengerRequest] = {}

    def register(self, request: PassengerRequest) -> None:
        """Register a new unique request."""

        if request.request_id in self._requests:
            raise ValueError("Duplicate request id: {}".format(request.request_id))
        if request.origin == request.destination:
            raise ValueError("Origin and destination must differ")
        if request.passenger_count <= 0:
            raise ValueError("Passenger count must be positive")
        self._requests[request.request_id] = request

    def get(self, request_id: str) -> PassengerRequest:
        """Return a registered request or raise KeyError."""

        return self._requests[request_id]

    def all_requests(self) -> List[PassengerRequest]:
        """Return all registered requests."""

        return list(self._requests.values())

    def waiting(self, now: float) -> List[PassengerRequest]:
        """Return requests that have arrived and remain unassigned."""

        return [request for request in self._requests.values()
                if request.status == RequestStatus.WAITING
                and request.requested_at <= now]

    def elapsed_waiting_times(self, now: float) -> Dict[str, float]:
        """Return current or final waiting time for each arrived request."""

        return {request.request_id: request.waiting_time(now)
                for request in self._requests.values() if request.requested_at <= now}

    def transition(self, request_id: str, new_status: RequestStatus, now: float,
                   vehicle_id: str = "") -> PassengerRequest:
        """Apply a legal transition and update its associated timestamps."""

        request = self.get(request_id)
        if new_status not in self._TRANSITIONS[request.status]:
            raise ValueError("Invalid request transition: {} -> {}".format(
                request.status.value, new_status.value
            ))
        request.status = new_status
        if new_status == RequestStatus.ASSIGNED:
            if not vehicle_id:
                raise ValueError("An assigned request requires a vehicle id")
            request.assigned_vehicle_id = vehicle_id
        elif new_status == RequestStatus.WAITING:
            request.assigned_vehicle_id = None
        elif new_status == RequestStatus.PICKED_UP:
            request.picked_up_at = now
        elif new_status == RequestStatus.COMPLETED:
            request.completed_at = now
        return request

    def overdue(self, now: float) -> List[PassengerRequest]:
        """Return waiting requests whose maximum wait has elapsed."""

        return [request for request in self.waiting(now)
                if request.waiting_time(now) >= request.maximum_wait_time]

    def group_waiting(self, now: float, by: str = "destination") -> Dict[str, List[PassengerRequest]]:
        """Group waiting requests by origin or destination."""

        if by not in ("origin", "destination"):
            raise ValueError("Grouping field must be origin or destination")
        groups: DefaultDict[str, List[PassengerRequest]] = defaultdict(list)
        for request in self.waiting(now):
            groups[getattr(request, by)].append(request)
        return dict(groups)

    def completed(self) -> List[PassengerRequest]:
        """Return completed request history."""

        return [request for request in self._requests.values()
                if request.status == RequestStatus.COMPLETED]

