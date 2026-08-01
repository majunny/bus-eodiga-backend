# -*- coding: utf-8 -*-
"""동부아파트입구 AI 교통약자 키오스크와 Render 공동 배차 연결.

필수 환경변수:
    BUS_EODIGA_KIOSK_KEY: Render의 MODI_KIOSK_API_KEY와 같은 값

선택 환경변수:
    OPENAI_API_KEY: 큰 소리 발생 시 캡처 이미지 안전 분석에 사용
    BUS_EODIGA_API_URL: 기본값 https://bus-eodiga-api.onrender.com
"""

from __future__ import annotations

import base64
import os
import queue
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import cv2
import httpx
from openai import OpenAI
from ultralytics import YOLO

from backend.modi_stops import MODI_BUS_STOPS, MODI_DEPOT_STOP_ID


API_URL = os.getenv("BUS_EODIGA_API_URL", "https://bus-eodiga-api.onrender.com")
KIOSK_API_KEY = os.getenv("BUS_EODIGA_KIOSK_KEY", "")
KIOSK_DEVICE_ID = os.getenv("BUS_EODIGA_KIOSK_DEVICE_ID", "dongbu-kiosk-01")
OPENAI_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o")

DEFAULT_MODEL_PATH = Path(__file__).with_name("26swbest2.pt")
ROOT_MODEL_PATH = Path(__file__).resolve().parents[2] / "26swbest2.pt"
if not DEFAULT_MODEL_PATH.is_file() and ROOT_MODEL_PATH.is_file():
    DEFAULT_MODEL_PATH = ROOT_MODEL_PATH
MODEL_PATH = Path(os.getenv("YOLO_MODEL_PATH", str(DEFAULT_MODEL_PATH))).expanduser()
CAMERA_ID = int(os.getenv("CAMERA_ID", "0"))
LOUD_SOUND_THRESHOLD = 90
LOUD_SOUND_RESET_THRESHOLD = 60
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"

DESTINATION_STOPS = [stop for stop in MODI_BUS_STOPS if stop["stop_id"] != MODI_DEPOT_STOP_ID]
USER_LABELS = {"yellow": "고령자", "mint": "장애인"}
MOBILITY_SUPPORT = {"yellow": "SENIOR", "mint": "WHEELCHAIR"}

is_running = True
current_user_type = "yellow"
current_destination_index = 0
screenshot_requested = threading.Event()
analysis_queue: queue.Queue[Path] = queue.Queue()
analysis_result_queue: queue.Queue[str] = queue.Queue()


class KioskApiClient:
    """키오스크 호출을 검증된 Render API를 통해 등록한다."""

    def __init__(self) -> None:
        if not KIOSK_API_KEY:
            raise RuntimeError("BUS_EODIGA_KIOSK_KEY 환경변수가 필요합니다.")
        self.client = httpx.Client(
            base_url=API_URL.rstrip("/"),
            headers={"X-Kiosk-Key": KIOSK_API_KEY},
            timeout=20.0,
        )

    def request_ride(self, destination_stop_id: str, user_type: str) -> dict:
        response = self.client.post(
            "/v1/modi-kiosk/ride-requests",
            headers={"Idempotency-Key": str(uuid.uuid4())},
            json={
                "device_id": KIOSK_DEVICE_ID,
                "destination_place_id": destination_stop_id,
                "passenger_count": 1,
                "mobility_support": MOBILITY_SUPPORT[user_type],
            },
        )
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.client.close()


def analyze_scene(image_path: Path) -> None:
    """캡처 사진을 분석하고 결과만 메인 하드웨어 스레드로 전달한다."""

    if not os.getenv("OPENAI_API_KEY"):
        analysis_result_queue.put("[주의] AI 키 없음")
        return
    try:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        client = OpenAI()
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 버스 정류장 안전 보조 요원입니다. 이미지만으로 확실하지 않은 상황은 "
                        "단정하지 마세요. 결과를 [위험], [주의], [안전] 중 하나로 시작하여 15자 이내로 답하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "큰 소리가 감지된 직후 정류장 사진입니다. 즉시 도움이 필요한지 평가하세요."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}},
                    ],
                },
            ],
            max_tokens=50,
            temperature=0.2,
        )
        result = (response.choices[0].message.content or "[주의] 확인 필요").strip()
        analysis_result_queue.put(result[:30])
    except Exception as error:
        print(f">> [OpenAI 분석 실패] {error}")
        analysis_result_queue.put("[주의] 직접 확인")


def webcam_worker() -> None:
    """카드 인식과 소음 발생 시점의 사진 캡처를 담당한다."""

    global current_user_type, is_running
    if not MODEL_PATH.is_file():
        print(
            ">> 카드 인식 모델이 없습니다: "
            f"{MODEL_PATH}\n"
            ">> 친구에게 26swbest2.pt를 받아 이 경로에 두거나 "
            "YOLO_MODEL_PATH 환경변수를 지정하세요."
        )
        is_running = False
        return
    model = YOLO(str(MODEL_PATH))
    camera = cv2.VideoCapture(CAMERA_ID)
    if not camera.isOpened():
        print(f">> {CAMERA_ID}번 카메라를 열 수 없습니다.")
        is_running = False
        return
    try:
        while is_running:
            success, frame = camera.read()
            if not success:
                time.sleep(0.02)
                continue
            if screenshot_requested.is_set():
                SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                image_path = SCREENSHOT_DIR / f"loud_sound_{datetime.now():%Y%m%d_%H%M%S_%f}.jpg"
                cv2.imwrite(str(image_path), frame)
                screenshot_requested.clear()
                analysis_queue.put(image_path)

            results = model(frame, conf=0.7, verbose=False)
            detected = {model.names[int(box.cls[0])] for box in results[0].boxes}
            if "senior_card" in detected:
                current_user_type = "yellow"
            elif "disabled_card" in detected:
                current_user_type = "mint"

            cv2.imshow("BUS 어디가 MODI 키오스크", results[0].plot())
            if cv2.waitKey(1) & 0xFF == ord("q"):
                is_running = False
    finally:
        camera.release()
        cv2.destroyAllWindows()


def analysis_worker() -> None:
    while is_running:
        try:
            image_path = analysis_queue.get(timeout=0.2)
        except queue.Empty:
            continue
        analyze_scene(image_path)


def main() -> None:
    global current_destination_index, is_running

    try:
        import modi_plus
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "MODI+ Python SDK(modi_plus)가 없습니다. 키트에서 제공한 SDK를 먼저 설치하세요."
        ) from error

    api = KioskApiClient()
    print("MODI+ 키오스크 모듈 연결 중...")
    bundle = modi_plus.MODIPlus()
    button = bundle.buttons[0]
    joystick = bundle.joysticks[0]
    display = bundle.displays[0]
    speaker = bundle.speakers[0]
    led = bundle.leds[0]
    if not bundle.envs:
        raise RuntimeError("연결된 MODI+ 환경 센서가 없습니다.")
    environment = bundle.envs[0]

    threading.Thread(target=webcam_worker, daemon=True).start()
    threading.Thread(target=analysis_worker, daemon=True).start()
    last_screen_key = None
    loud_sound_armed = True
    alert_until = 0.0

    def show_selection() -> None:
        nonlocal last_screen_key
        destination = DESTINATION_STOPS[current_destination_index]
        screen_key = (current_user_type, destination["stop_id"])
        if screen_key == last_screen_key or time.monotonic() < alert_until:
            return
        display.reset()
        display.write_text(f"[{USER_LABELS[current_user_type]}] {destination['name']}")
        led.rgb = (255, 255, 0) if current_user_type == "yellow" else (0, 255, 180)
        last_screen_key = screen_key

    print("--- 동부아파트입구 AI 안심 승차 키오스크 시작 ---")
    try:
        while is_running:
            volume = environment.volume
            if loud_sound_armed and volume >= LOUD_SOUND_THRESHOLD:
                screenshot_requested.set()
                loud_sound_armed = False
                alert_until = time.monotonic() + 3.0
                display.reset()
                display.write_text("[경고] 현장 확인중")
                led.rgb = (255, 0, 0)
                speaker.play_music("Siren", 70)
            elif not loud_sound_armed and volume <= LOUD_SOUND_RESET_THRESHOLD:
                loud_sound_armed = True

            try:
                analysis_result = analysis_result_queue.get_nowait()
            except queue.Empty:
                analysis_result = None
            if analysis_result:
                alert_until = time.monotonic() + 5.0
                display.reset()
                display.write_text(analysis_result)
                print(f">> [현장 안전 분석] {analysis_result}")

            show_selection()
            direction = joystick.direction
            if direction in {"right", "left"}:
                delta = 1 if direction == "right" else -1
                current_destination_index = (current_destination_index + delta) % len(DESTINATION_STOPS)
                last_screen_key = None
                while is_running and joystick.direction != "origin":
                    time.sleep(0.05)

            if button.clicked:
                destination = DESTINATION_STOPS[current_destination_index]
                print(f">> [승차 요청] 동부아파트입구 → {destination['name']}")
                try:
                    record = api.request_ride(destination["stop_id"], current_user_type)
                    matched = record.get("matched_passenger_count", 0)
                    required = record.get("demo_group_size", 3)
                    display.reset()
                    display.write_text(f"[요청완료] {matched}/{required}명")
                    led.rgb = (0, 255, 0)
                    speaker.play_music("Complete 1", 50)
                    print(f">> Render 저장 완료: {record['request_id']} · {matched}/{required}명")
                except Exception as error:
                    display.reset()
                    display.write_text("[오류] 요청 실패")
                    led.rgb = (255, 0, 0)
                    print(f">> [Render 요청 실패] {error}")
                alert_until = time.monotonic() + 2.0
                last_screen_key = None
                time.sleep(0.5)

            time.sleep(0.05)
    except KeyboardInterrupt:
        print("종료합니다.")
    finally:
        is_running = False
        api.close()
        display.reset()


if __name__ == "__main__":
    main()
