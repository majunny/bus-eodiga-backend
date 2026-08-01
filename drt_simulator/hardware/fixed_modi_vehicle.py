"""친구의 별도 주행 파일 없이 고정 MODI 운행을 실행하는 PyMODI+ 드라이버.

고정 경로:
    동부아파트(P1 승차) → 롯데마트(P2 승차) → 강남초(P2 하차) → 공업탑(P1 하차)

첫 실행은 차량을 들어 올린 상태에서 방향·바퀴 회전을 확인한다.
"""

from __future__ import annotations

import math
import os
import time
from typing import Any

import httpx
import modi_plus


API_URL = os.getenv("BUS_EODIGA_API_URL", "https://bus-eodiga-api.onrender.com")
VEHICLE_ID = os.getenv("BUS_EODIGA_VEHICLE_ID", "modi-bus-01")
VEHICLE_KEY = os.getenv("BUS_EODIGA_VEHICLE_KEY", "")
POLL_SECONDS = float(os.getenv("BUS_EODIGA_POLL_SECONDS", "2"))
DWELL_SECONDS = float(os.getenv("BUS_EODIGA_DWELL_SECONDS", "2"))
DRIVE_SPEED = int(os.getenv("MODI_DRIVE_SPEED", "30"))
TURN_SPEED = int(os.getenv("MODI_TURN_SPEED", "28"))
CM_PER_SECOND = float(os.getenv("MODI_CM_PER_SECOND", "10"))
START_HEADING = float(os.getenv("MODI_START_HEADING", "180"))
MOTOR_SIGN_FOR_POSITIVE_YAW = -1

FRONT_LEFT_INDEX = 2
FRONT_RIGHT_INDEX = 0
REAR_LEFT_INDEX = 1
REAR_RIGHT_INDEX = 3

# 원본 모형 지도 사진의 정류장 중심 좌표(정규화 x, y)입니다.
BOARD_POINTS = {
    "31208": (0.774, 0.798),  # 동부아파트입구, 차고지
    "64201": (0.346, 0.504),  # 롯데마트(롯데백화점 위치)
    "40410": (0.547, 0.302),  # 강남초등학교
    "40404": (0.181, 0.302),  # 공업탑
}
STOP_NAMES = {
    "31208": "동부아파트입구",
    "64201": "롯데마트",
    "40410": "강남초등학교",
    "40404": "공업탑",
}
EXPECTED_STOP_IDS = ["31208", "64201", "40410", "40404"]


def wrapped_delta(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


def normalize_heading(angle: float) -> float:
    return angle % 360.0


class FixedModiVehicle:
    def __init__(self) -> None:
        if not VEHICLE_KEY:
            raise RuntimeError("BUS_EODIGA_VEHICLE_KEY 환경변수가 필요합니다.")
        self.bundle: Any = None
        self.wheels: dict[str, Any] = {}
        self.imu: Any = None
        self.reference_yaw: float | None = None
        self.client = httpx.Client(
            base_url=API_URL.rstrip("/"),
            headers={"X-Vehicle-Key": VEHICLE_KEY},
            timeout=20.0,
        )

    def connect(self) -> None:
        self.bundle = modi_plus.MODIPlus()
        if len(self.bundle.motors) < 4 or not self.bundle.imus:
            raise RuntimeError("MODI+ 모터 4개와 IMU 1개가 모두 필요합니다.")
        self.wheels = {
            "front_left": self.bundle.motors[FRONT_LEFT_INDEX],
            "front_right": self.bundle.motors[FRONT_RIGHT_INDEX],
            "rear_left": self.bundle.motors[REAR_LEFT_INDEX],
            "rear_right": self.bundle.motors[REAR_RIGHT_INDEX],
        }
        self.imu = self.bundle.imus[0]
        time.sleep(1.0)
        self.reference_yaw = float(self.imu.angle_z)
        print(
            f"MODI 차량 연결: 모터 {len(self.bundle.motors)}개, IMU {self.imu.id} · "
            f"초기 방위 {START_HEADING:.1f}° 기준"
        )
        print("차량 앞을 모형 지도에서 서쪽 방향으로 맞춘 뒤 운행합니다.")

    def set_wheels(self, left: int, right: int) -> None:
        self.wheels["front_left"].speed = left
        self.wheels["rear_left"].speed = left
        self.wheels["front_right"].speed = right
        self.wheels["rear_right"].speed = right

    def stop(self) -> None:
        if not self.wheels:
            return
        for _ in range(2):
            for wheel in self.wheels.values():
                wheel.speed = 0
            for wheel in self.wheels.values():
                wheel.stop()
            time.sleep(0.08)

    def current_heading(self) -> float:
        if self.reference_yaw is None:
            raise RuntimeError("IMU 기준 방위가 설정되지 않았습니다.")
        return normalize_heading(START_HEADING + wrapped_delta(float(self.imu.angle_z), self.reference_yaw))

    def rotate_to(self, target: float) -> None:
        started = time.monotonic()
        while True:
            current = self.current_heading()
            error = wrapped_delta(target, current)
            if abs(error) <= 6.0:
                self.stop()
                return
            if time.monotonic() - started > 15.0:
                self.stop()
                raise RuntimeError(f"회전 제한시간 초과: 목표={target:.1f}°, 현재={current:.1f}°")
            direction = (1 if error > 0 else -1) * MOTOR_SIGN_FOR_POSITIVE_YAW
            # 좌우 바퀴를 같은 방향으로 돌리면 제자리 회전합니다.
            self.set_wheels(TURN_SPEED * direction, TURN_SPEED * direction)
            time.sleep(0.02)

    def drive_segment(self, start_id: str, end_id: str) -> None:
        start = BOARD_POINTS[start_id]
        end = BOARD_POINTS[end_id]
        dx = (end[0] - start[0]) * 120.0
        dy = (end[1] - start[1]) * 80.0
        distance_cm = math.hypot(dx, dy)
        target_heading = normalize_heading(math.degrees(math.atan2(-dy, dx)))
        self.rotate_to(target_heading)
        seconds = max(0.2, distance_cm / CM_PER_SECOND)
        print(f"  {STOP_NAMES[start_id]} → {STOP_NAMES[end_id]} · {distance_cm:.1f}cm · {seconds:.1f}초")
        self.set_wheels(DRIVE_SPEED, -DRIVE_SPEED)
        try:
            time.sleep(seconds)
        finally:
            self.stop()

    def execute_trip(self, trip: dict[str, Any]) -> None:
        trip_id = str(trip["trip_id"])
        claimed = self.client.post(f"/v1/vehicles/{VEHICLE_ID}/trips/{trip_id}/claim")
        claimed.raise_for_status()
        steps = list(claimed.json().get("route_steps") or [])
        stop_ids = [str(step["place"]["place_id"]) for step in steps]
        if stop_ids != EXPECTED_STOP_IDS:
            raise RuntimeError(f"고정 경로가 아닙니다: {stop_ids} != {EXPECTED_STOP_IDS}")
        print(f"고정 MODI 운행 시작: {trip_id}")
        for index, step in enumerate(steps):
            stop_id = str(step["place"]["place_id"])
            self.client.post(
                f"/v1/vehicles/{VEHICLE_ID}/trips/{trip_id}/progress",
                json={"stop_index": index, "phase": "EN_ROUTE"},
            ).raise_for_status()
            if index > 0:
                self.drive_segment(EXPECTED_STOP_IDS[index - 1], stop_id)
            self.client.post(
                f"/v1/vehicles/{VEHICLE_ID}/trips/{trip_id}/progress",
                json={"stop_index": index, "phase": "ARRIVED"},
            ).raise_for_status()
            time.sleep(DWELL_SECONDS)
            phase = "BOARDED" if step["type"] == "PICKUP" else "DROPPED_OFF"
            self.client.post(
                f"/v1/vehicles/{VEHICLE_ID}/trips/{trip_id}/progress",
                json={"stop_index": index, "phase": phase},
            ).raise_for_status()
        self.client.post(
            f"/v1/vehicles/{VEHICLE_ID}/trips/{trip_id}/progress",
            json={"stop_index": len(steps) - 1, "phase": "COMPLETED"},
        ).raise_for_status()
        print("고정 MODI 운행 완료")

    def run(self) -> None:
        self.connect()
        try:
            while True:
                response = self.client.get(f"/v1/vehicles/{VEHICLE_ID}/trips/next")
                response.raise_for_status()
                trip = response.json().get("trip")
                if trip:
                    self.execute_trip(trip)
                    return
                time.sleep(POLL_SECONDS)
        finally:
            self.stop()
            self.client.close()
            if self.bundle is not None:
                self.bundle.close()


if __name__ == "__main__":
    FixedModiVehicle().run()
