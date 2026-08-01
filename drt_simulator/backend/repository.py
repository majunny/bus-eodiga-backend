"""호출 저장소의 메모리 및 Firestore 구현."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Optional
from uuid import uuid4

from firebase_admin import firestore

from backend.models import RideRequestRecord, RideStatus


class RideRepository(ABC):
    """호출 데이터 저장소 추상 인터페이스."""

    @abstractmethod
    def create(self, record: RideRequestRecord, idempotency_key: str) -> RideRequestRecord:
        """호출을 한 번만 저장한다."""

    @abstractmethod
    def get(self, request_id: str) -> Optional[RideRequestRecord]:
        """호출 ID로 문서를 조회한다."""

    @abstractmethod
    def cancel(self, request_id: str, user_id: str) -> Optional[RideRequestRecord]:
        """사용자가 소유한 대기 호출을 취소한다."""

    @abstractmethod
    def join_demo_pool(
        self,
        request_id: str,
        user_id: str,
        vehicle_id: str,
        group_size: int,
        queue_ttl_seconds: float = 180.0,
    ) -> Optional[RideRequestRecord]:
        """설정된 인원의 시연 승객이 모이면 함께 배정한다."""

    @abstractmethod
    def claim_demo_trip_simulation(self, trip_id: str) -> Optional[dict]:
        """한 서버 작업만 운행 시뮬레이션을 시작하도록 선점한다."""

    @abstractmethod
    def find_available_demo_trip(self, vehicle_id: str) -> Optional[dict]:
        """차량이 아직 선점하지 않은 가장 오래된 운행을 반환한다."""

    @abstractmethod
    def get_demo_trip(self, trip_id: str) -> Optional[dict]:
        """공동 운행 ID로 내부 차량 운행 문서를 조회한다."""

    @abstractmethod
    def update_demo_trip_progress(
        self,
        trip_id: str,
        stop_index: int,
        phase: str,
        request_id: Optional[str] = None,
        request_status: Optional[RideStatus] = None,
    ) -> None:
        """공동 운행 진행 상태를 모든 참여 호출에 기록한다."""


class MemoryRideRepository(RideRepository):
    """Firebase 없이 로컬 테스트에 사용하는 저장소."""

    def __init__(self) -> None:
        self._records: Dict[str, RideRequestRecord] = {}
        self._idempotency: Dict[str, str] = {}
        self._demo_waiting_ids: Dict[str, list[str]] = {}
        self._demo_trips: Dict[str, dict] = {}
        self._lock = Lock()

    def create(self, record: RideRequestRecord, idempotency_key: str) -> RideRequestRecord:
        """프로세스 내 잠금으로 중복 생성을 방지한다."""

        with self._lock:
            existing_id = self._idempotency.get(idempotency_key)
            if existing_id:
                return self._records[existing_id]
            self._records[record.request_id] = record
            self._idempotency[idempotency_key] = record.request_id
            return record

    def get(self, request_id: str) -> Optional[RideRequestRecord]:
        """메모리에서 호출을 조회한다."""

        return self._records.get(request_id)

    def cancel(self, request_id: str, user_id: str) -> Optional[RideRequestRecord]:
        """WAITING 호출만 취소 상태로 변경한다."""

        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.user_id != user_id:
                return None
            if record.status != RideStatus.WAITING:
                return record
            updated = record.model_copy(update={"status": RideStatus.CANCELLED, "updated_at": datetime.now(timezone.utc)})
            self._records[request_id] = updated
            return updated

    def join_demo_pool(
        self,
        request_id: str,
        user_id: str,
        vehicle_id: str,
        group_size: int,
        queue_ttl_seconds: float = 180.0,
    ) -> Optional[RideRequestRecord]:
        """본인과 동반 인원을 합산해 출발 기준을 충족하면 공동 배차한다."""

        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.user_id != user_id:
                return None
            if record.status != RideStatus.WAITING:
                return record
            now = datetime.now(timezone.utc)
            waiting_ids = self._demo_waiting_ids.get(vehicle_id, [])
            waiting = [
                self._records[waiting_id]
                for waiting_id in waiting_ids
                if waiting_id in self._records
                and self._records[waiting_id].status == RideStatus.WAITING
                and (now - self._records[waiting_id].updated_at).total_seconds() <= queue_ttl_seconds
            ]
            if request_id in {item.request_id for item in waiting}:
                return record
            if user_id in {item.user_id for item in waiting}:
                return record
            waiting.append(record)
            self._demo_waiting_ids[vehicle_id] = [item.request_id for item in waiting]
            matched_passenger_count = sum(item.passenger_count for item in waiting)
            for participant in waiting:
                self._records[participant.request_id] = participant.model_copy(update={
                    "matched_passenger_count": matched_passenger_count,
                    "demo_group_size": group_size,
                    "updated_at": now,
                })
            if matched_passenger_count < group_size:
                return self._records[request_id]

            trip_id = str(uuid4())
            route_plan = _build_demo_route_plan(waiting)
            route_stops = [step["place"] for step in route_plan]
            for matched in waiting:
                self._records[matched.request_id] = matched.model_copy(update={
                    "status": RideStatus.ASSIGNED,
                    "assigned_vehicle_id": vehicle_id,
                    "demo_trip_id": trip_id,
                    "matched_passenger_count": matched_passenger_count,
                    "demo_group_size": group_size,
                    "demo_route_stops": route_stops,
                    "demo_current_stop_index": -1,
                    "demo_trip_phase": "READY",
                    "updated_at": now,
                })
            self._demo_trips[trip_id] = {
                "trip_id": trip_id,
                "vehicle_id": vehicle_id,
                "request_ids": [item.request_id for item in waiting],
                "route_steps": [
                    {**step, "place": step["place"].model_dump(mode="json")}
                    for step in route_plan
                ],
                "simulation_started": False,
                "phase": "READY",
            }
            self._demo_waiting_ids[vehicle_id] = []
            return self._records[request_id]

    def claim_demo_trip_simulation(self, trip_id: str) -> Optional[dict]:
        """메모리 운행을 한 번만 시작한다."""

        with self._lock:
            trip = self._demo_trips.get(trip_id)
            if trip is None or trip.get("simulation_started"):
                return None
            trip["simulation_started"] = True
            trip["phase"] = "RUNNING"
            return dict(trip)

    def find_available_demo_trip(self, vehicle_id: str) -> Optional[dict]:
        """메모리 운행 중 해당 차량이 아직 선점하지 않은 첫 운행을 반환한다."""

        with self._lock:
            for trip in self._demo_trips.values():
                if trip.get("vehicle_id") == vehicle_id and not trip.get("simulation_started"):
                    return dict(trip)
        return None

    def get_demo_trip(self, trip_id: str) -> Optional[dict]:
        """메모리에서 공동 운행을 조회한다."""

        trip = self._demo_trips.get(trip_id)
        return dict(trip) if trip is not None else None

    def update_demo_trip_progress(
        self,
        trip_id: str,
        stop_index: int,
        phase: str,
        request_id: Optional[str] = None,
        request_status: Optional[RideStatus] = None,
    ) -> None:
        """메모리 참여 호출 전체에 동일한 진행 상태를 기록한다."""

        with self._lock:
            trip = self._demo_trips.get(trip_id)
            if trip is None:
                return
            trip["phase"] = phase
            trip["current_stop_index"] = stop_index
            for participant_id in trip["request_ids"]:
                record = self._records[participant_id]
                update = {
                    "demo_current_stop_index": stop_index,
                    "demo_trip_phase": phase,
                    "updated_at": datetime.now(timezone.utc),
                }
                if participant_id == request_id and request_status is not None:
                    update["status"] = request_status
                self._records[participant_id] = record.model_copy(update=update)


class FirestoreRideRepository(RideRepository):
    """Firestore Transaction을 사용하는 운영 저장소."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client
        self._collection = client.collection("ride_requests")
        self._idempotency = client.collection("ride_idempotency")
        self._demo_dispatch = client.collection("demo_dispatch")
        self._demo_trips = client.collection("demo_trips")

    def create(self, record: RideRequestRecord, idempotency_key: str) -> RideRequestRecord:
        """Idempotency 문서와 호출 문서를 원자적으로 생성한다."""

        transaction = self._client.transaction()
        key_ref = self._idempotency.document(idempotency_key)
        request_ref = self._collection.document(record.request_id)

        @firestore.transactional
        def create_in_transaction(current: firestore.Transaction) -> str:
            snapshot = key_ref.get(transaction=current)
            if snapshot.exists:
                return str(snapshot.to_dict()["request_id"])
            current.set(request_ref, record.model_dump(mode="json"))
            current.set(key_ref, {"request_id": record.request_id, "user_id": record.user_id})
            return record.request_id

        saved_id = create_in_transaction(transaction)
        saved = self.get(saved_id)
        if saved is None:
            raise RuntimeError("Firestore request was not persisted")
        return saved

    def get(self, request_id: str) -> Optional[RideRequestRecord]:
        """Firestore 호출 문서를 조회한다."""

        snapshot = self._collection.document(request_id).get()
        if not snapshot.exists:
            return None
        return RideRequestRecord.model_validate(snapshot.to_dict())

    def cancel(self, request_id: str, user_id: str) -> Optional[RideRequestRecord]:
        """소유권과 상태를 Transaction 안에서 확인하고 취소한다."""

        document = self._collection.document(request_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def cancel_in_transaction(current: firestore.Transaction) -> bool:
            snapshot = document.get(transaction=current)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict()
            if data.get("user_id") != user_id:
                return False
            if data.get("status") == RideStatus.WAITING.value:
                current.update(document, {
                    "status": RideStatus.CANCELLED.value,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            return True

        if not cancel_in_transaction(transaction):
            return None
        return self.get(request_id)

    def join_demo_pool(
        self,
        request_id: str,
        user_id: str,
        vehicle_id: str,
        group_size: int,
        queue_ttl_seconds: float = 180.0,
    ) -> Optional[RideRequestRecord]:
        """Firestore 대기열에서 여러 사용자 호출을 원자적으로 공동 배차한다."""

        document = self._collection.document(request_id)
        demo_queue = self._demo_dispatch.document(f"queue_{vehicle_id}")
        transaction = self._client.transaction()

        @firestore.transactional
        def match_in_transaction(current: firestore.Transaction) -> bool:
            snapshot = document.get(transaction=current)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict()
            if data.get("user_id") != user_id:
                return False
            if data.get("status") != RideStatus.WAITING.value:
                return True

            queue_snapshot = demo_queue.get(transaction=current)
            queue_data = queue_snapshot.to_dict() if queue_snapshot.exists else {}
            waiting_ids = list(queue_data.get("request_ids") or [])
            if not waiting_ids and queue_data.get("request_id"):
                waiting_ids = [str(queue_data["request_id"])]
            waiting_refs = [self._collection.document(str(waiting_id)) for waiting_id in waiting_ids if waiting_id != request_id]
            waiting_snapshots = [waiting_ref.get(transaction=current) for waiting_ref in waiting_refs]
            participants: list[tuple] = []
            now_datetime = datetime.now(timezone.utc)
            seen_users = {user_id}
            for waiting_ref, waiting_snapshot in zip(waiting_refs, waiting_snapshots):
                if not waiting_snapshot.exists:
                    continue
                waiting_data = waiting_snapshot.to_dict()
                waiting_user = waiting_data.get("user_id")
                waiting_record = RideRequestRecord.model_validate(waiting_data)
                if waiting_data.get("status") != RideStatus.WAITING.value or not waiting_user or waiting_user in seen_users:
                    continue
                if (now_datetime - waiting_record.updated_at).total_seconds() > queue_ttl_seconds:
                    continue
                seen_users.add(waiting_user)
                participants.append((waiting_ref, waiting_record))

            if request_id in waiting_ids:
                return True
            participants.append((document, RideRequestRecord.model_validate(data)))
            now = now_datetime.isoformat()
            matched_passenger_count = sum(participant.passenger_count for _, participant in participants)
            if matched_passenger_count < group_size:
                waiting_update = {
                    "matched_passenger_count": matched_passenger_count,
                    "demo_group_size": group_size,
                    "updated_at": now,
                }
                for participant_ref, _ in participants:
                    current.update(participant_ref, waiting_update)
                current.set(demo_queue, {
                    "request_ids": [participant.request_id for _, participant in participants],
                    "user_ids": [participant.user_id for _, participant in participants],
                    "group_size": group_size,
                    "updated_at": now,
                })
                return True

            records = [participant for _, participant in participants]
            route_plan = _build_demo_route_plan(records)
            route_stops = [step["place"].model_dump(mode="json") for step in route_plan]
            trip_id = str(uuid4())
            shared_update = {
                "status": RideStatus.ASSIGNED.value,
                "assigned_vehicle_id": vehicle_id,
                "demo_trip_id": trip_id,
                "matched_passenger_count": matched_passenger_count,
                "demo_group_size": group_size,
                "demo_route_stops": route_stops,
                "demo_current_stop_index": -1,
                "demo_trip_phase": "READY",
                "updated_at": now,
            }
            for participant_ref, _ in participants:
                current.update(participant_ref, shared_update)
            current.set(self._demo_trips.document(trip_id), {
                "trip_id": trip_id,
                "vehicle_id": vehicle_id,
                "request_ids": [record.request_id for record in records],
                "user_ids": [record.user_id for record in records],
                "route_steps": [
                    {**step, "place": step["place"].model_dump(mode="json")}
                    for step in route_plan
                ],
                "simulation_started": False,
                "phase": "READY",
                "current_stop_index": -1,
                "created_at": now,
                "updated_at": now,
            })
            current.delete(demo_queue)
            return True

        if not match_in_transaction(transaction):
            return None
        return self.get(request_id)

    def claim_demo_trip_simulation(self, trip_id: str) -> Optional[dict]:
        """Firestore Transaction으로 시뮬레이션 실행권을 선점한다."""

        document = self._demo_trips.document(trip_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def claim(current: firestore.Transaction) -> Optional[dict]:
            snapshot = document.get(transaction=current)
            if not snapshot.exists:
                return None
            data = snapshot.to_dict()
            if data.get("simulation_started"):
                return None
            current.update(document, {
                "simulation_started": True,
                "phase": "RUNNING",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            return {**data, "simulation_started": True, "phase": "RUNNING"}

        return claim(transaction)

    def find_available_demo_trip(self, vehicle_id: str) -> Optional[dict]:
        """Firestore에서 해당 차량의 미선점 운행을 생성 순서로 반환한다."""

        candidates = []
        for snapshot in self._demo_trips.where("vehicle_id", "==", vehicle_id).stream():
            data = snapshot.to_dict()
            if not data.get("simulation_started") and data.get("phase") != "COMPLETED":
                candidates.append(data)
        if not candidates:
            return None
        return min(candidates, key=lambda item: str(item.get("created_at") or ""))

    def get_demo_trip(self, trip_id: str) -> Optional[dict]:
        """Firestore에서 공동 운행 문서를 조회한다."""

        snapshot = self._demo_trips.document(trip_id).get()
        return snapshot.to_dict() if snapshot.exists else None

    def update_demo_trip_progress(
        self,
        trip_id: str,
        stop_index: int,
        phase: str,
        request_id: Optional[str] = None,
        request_status: Optional[RideStatus] = None,
    ) -> None:
        """Batch로 모든 참여 호출과 내부 운행 문서를 함께 갱신한다."""

        trip_ref = self._demo_trips.document(trip_id)
        trip_snapshot = trip_ref.get()
        if not trip_snapshot.exists:
            return
        trip = trip_snapshot.to_dict()
        now = datetime.now(timezone.utc).isoformat()
        batch = self._client.batch()
        for participant_id in trip.get("request_ids") or []:
            update = {
                "demo_current_stop_index": stop_index,
                "demo_trip_phase": phase,
                "updated_at": now,
            }
            if participant_id == request_id and request_status is not None:
                update["status"] = request_status.value
            batch.update(self._collection.document(str(participant_id)), update)
        batch.update(trip_ref, {
            "current_stop_index": stop_index,
            "phase": phase,
            "updated_at": now,
        })
        batch.commit()


def _build_demo_route_stops(records: list[RideRequestRecord]) -> list:
    """서쪽에서 동쪽으로 모든 승차지를 거친 뒤 모든 목적지로 운행한다."""

    pickup_order = sorted(records, key=lambda item: item.pickup.location.longitude)
    destination_order = sorted(records, key=lambda item: item.destination.location.longitude)
    return [item.pickup for item in pickup_order] + [item.destination for item in destination_order]


def _build_demo_route_plan(records: list[RideRequestRecord]) -> list[dict]:
    """각 경유지를 소유 호출·승하차 종류와 함께 반환한다."""

    pickup_order = sorted(records, key=lambda item: item.pickup.location.longitude)
    destination_order = sorted(records, key=lambda item: item.destination.location.longitude)
    return [
        {"request_id": item.request_id, "type": "PICKUP", "order": index + 1, "place": item.pickup}
        for index, item in enumerate(pickup_order)
    ] + [
        {"request_id": item.request_id, "type": "DROPOFF", "order": index + 1, "place": item.destination}
        for index, item in enumerate(destination_order)
    ]
