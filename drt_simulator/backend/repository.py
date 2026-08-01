"""호출 저장소의 메모리 및 Firestore 구현."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, Optional

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
    def assign_demo(self, request_id: str, user_id: str, vehicle_id: str) -> Optional[RideRequestRecord]:
        """시연 중 사용자의 대기 호출에 차량을 배정한다."""


class MemoryRideRepository(RideRepository):
    """Firebase 없이 로컬 테스트에 사용하는 저장소."""

    def __init__(self) -> None:
        self._records: Dict[str, RideRequestRecord] = {}
        self._idempotency: Dict[str, str] = {}
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

    def assign_demo(self, request_id: str, user_id: str, vehicle_id: str) -> Optional[RideRequestRecord]:
        """WAITING 호출을 ASSIGNED 상태로 변경한다."""

        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.user_id != user_id:
                return None
            if record.status != RideStatus.WAITING:
                return record
            updated = record.model_copy(update={
                "status": RideStatus.ASSIGNED,
                "assigned_vehicle_id": vehicle_id,
                "updated_at": datetime.now(timezone.utc),
            })
            self._records[request_id] = updated
            return updated


class FirestoreRideRepository(RideRepository):
    """Firestore Transaction을 사용하는 운영 저장소."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client
        self._collection = client.collection("ride_requests")
        self._idempotency = client.collection("ride_idempotency")

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

    def assign_demo(self, request_id: str, user_id: str, vehicle_id: str) -> Optional[RideRequestRecord]:
        """소유권과 WAITING 상태를 확인한 뒤 시연 차량을 배정한다."""

        document = self._collection.document(request_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def assign_in_transaction(current: firestore.Transaction) -> bool:
            snapshot = document.get(transaction=current)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict()
            if data.get("user_id") != user_id:
                return False
            if data.get("status") == RideStatus.WAITING.value:
                current.update(document, {
                    "status": RideStatus.ASSIGNED.value,
                    "assigned_vehicle_id": vehicle_id,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            return True

        if not assign_in_transaction(transaction):
            return None
        return self.get(request_id)
