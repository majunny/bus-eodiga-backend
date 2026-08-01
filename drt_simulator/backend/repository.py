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
    def join_demo_pool(self, request_id: str, user_id: str, vehicle_id: str) -> Optional[RideRequestRecord]:
        """시연 대기열에 참여시키고 두 승객이 모이면 함께 배정한다."""


class MemoryRideRepository(RideRepository):
    """Firebase 없이 로컬 테스트에 사용하는 저장소."""

    def __init__(self) -> None:
        self._records: Dict[str, RideRequestRecord] = {}
        self._idempotency: Dict[str, str] = {}
        self._demo_waiting_id: Optional[str] = None
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

    def join_demo_pool(self, request_id: str, user_id: str, vehicle_id: str) -> Optional[RideRequestRecord]:
        """첫 승객은 대기시키고 두 번째 승객과 같은 차량에 배정한다."""

        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.user_id != user_id:
                return None
            if record.status != RideStatus.WAITING or record.matched_passenger_count == 2:
                return record
            waiting = self._records.get(self._demo_waiting_id or "")
            if waiting is None or waiting.status != RideStatus.WAITING:
                waiting = None
                self._demo_waiting_id = None
            if waiting is None or waiting.request_id == request_id or waiting.user_id == user_id:
                updated = record.model_copy(update={
                    "matched_passenger_count": 1,
                    "updated_at": datetime.now(timezone.utc),
                })
                self._records[request_id] = updated
                if waiting is None:
                    self._demo_waiting_id = request_id
                return updated

            trip_id = str(uuid4())
            route_stops = _build_demo_route_stops(waiting, record)
            now = datetime.now(timezone.utc)
            for matched in (waiting, record):
                self._records[matched.request_id] = matched.model_copy(update={
                    "status": RideStatus.ASSIGNED,
                    "assigned_vehicle_id": vehicle_id,
                    "demo_trip_id": trip_id,
                    "matched_passenger_count": 2,
                    "demo_route_stops": route_stops,
                    "updated_at": now,
                })
            self._demo_waiting_id = None
            return self._records[request_id]


class FirestoreRideRepository(RideRepository):
    """Firestore Transaction을 사용하는 운영 저장소."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client
        self._collection = client.collection("ride_requests")
        self._idempotency = client.collection("ride_idempotency")
        self._demo_queue = client.collection("demo_dispatch").document("pair_queue")

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

    def join_demo_pool(self, request_id: str, user_id: str, vehicle_id: str) -> Optional[RideRequestRecord]:
        """Firestore 대기열에서 두 사용자 호출을 원자적으로 공동 배차한다."""

        document = self._collection.document(request_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def match_in_transaction(current: firestore.Transaction) -> bool:
            snapshot = document.get(transaction=current)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict()
            if data.get("user_id") != user_id:
                return False
            if data.get("status") != RideStatus.WAITING.value or data.get("matched_passenger_count") == 2:
                return True

            queue_snapshot = self._demo_queue.get(transaction=current)
            waiting_id = queue_snapshot.to_dict().get("request_id") if queue_snapshot.exists else None
            waiting_snapshot = None
            waiting_ref = None
            if waiting_id and waiting_id != request_id:
                waiting_ref = self._collection.document(str(waiting_id))
                waiting_snapshot = waiting_ref.get(transaction=current)

            waiting_data = waiting_snapshot.to_dict() if waiting_snapshot and waiting_snapshot.exists else None
            can_pair = (
                waiting_data is not None
                and waiting_data.get("status") == RideStatus.WAITING.value
                and waiting_data.get("user_id") != user_id
            )
            now = datetime.now(timezone.utc).isoformat()
            if not can_pair or waiting_ref is None:
                current.update(document, {"matched_passenger_count": 1, "updated_at": now})
                if not waiting_id or waiting_data is None or waiting_data.get("status") != RideStatus.WAITING.value:
                    current.set(self._demo_queue, {"request_id": request_id, "user_id": user_id, "updated_at": now})
                return True

            waiting_record = RideRequestRecord.model_validate(waiting_data)
            current_record = RideRequestRecord.model_validate(data)
            route_stops = [stop.model_dump(mode="json") for stop in _build_demo_route_stops(waiting_record, current_record)]
            trip_id = str(uuid4())
            shared_update = {
                "status": RideStatus.ASSIGNED.value,
                "assigned_vehicle_id": vehicle_id,
                "demo_trip_id": trip_id,
                "matched_passenger_count": 2,
                "demo_route_stops": route_stops,
                "updated_at": now,
            }
            current.update(waiting_ref, shared_update)
            current.update(document, shared_update)
            current.delete(self._demo_queue)
            return True

        if not match_in_transaction(transaction):
            return None
        return self.get(request_id)


def _build_demo_route_stops(first: RideRequestRecord, second: RideRequestRecord) -> list:
    """서쪽에서 동쪽으로 두 승차지를 거친 뒤 두 목적지로 운행한다."""

    records = [first, second]
    pickup_order = sorted(records, key=lambda item: item.pickup.location.longitude)
    destination_order = sorted(records, key=lambda item: item.destination.location.longitude)
    return [item.pickup for item in pickup_order] + [item.destination for item in destination_order]
