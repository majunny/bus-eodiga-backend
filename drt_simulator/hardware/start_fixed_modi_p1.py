"""고정 MODI 시연의 P1(동부아파트 출발) 자동 호출을 한 번 등록한다.

P1은 친구 PC에서 이 스크립트를 한 번 실행하고, P2는 Android MODI 화면에서
롯데마트(롯데백화점 위치) 승차 → 강남초등학교 하차를 호출한다.
"""

from __future__ import annotations

import os
import uuid

import httpx


API_URL = os.getenv("BUS_EODIGA_API_URL", "https://bus-eodiga-api.onrender.com")
KIOSK_KEY = os.getenv("BUS_EODIGA_KIOSK_KEY", "")
DEVICE_ID = os.getenv("BUS_EODIGA_P1_DEVICE_ID", "fixed-demo-p1")


def main() -> None:
    if not KIOSK_KEY:
        raise SystemExit("BUS_EODIGA_KIOSK_KEY 환경변수가 필요합니다.")
    response = httpx.post(
        f"{API_URL.rstrip('/')}/v1/modi-kiosk/ride-requests",
        headers={
            "X-Kiosk-Key": KIOSK_KEY,
            "Idempotency-Key": str(uuid.uuid4()),
        },
        json={
            "device_id": DEVICE_ID,
            "destination_place_id": "40404",
            "passenger_count": 1,
            "mobility_support": "STANDARD",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    record = response.json()
    print(
        "P1 호출 등록: 동부아파트입구 승차 → 공업탑 하차 · "
        f"상태={record['status']} · 인원={record['matched_passenger_count']}/2"
    )
    print("이제 Android에서 P2의 MODI 호출을 등록하세요.")


if __name__ == "__main__":
    main()
