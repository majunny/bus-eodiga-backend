# MODI+ 미니 자동차 백엔드 연결

## 고정 2인 시연(P1 자동 + P2 Android)

친구 파일 없이 먼저 배차 시나리오만 시작할 때는 P1 자동 호출을 한 번 등록합니다.

```bash
export BUS_EODIGA_KIOSK_KEY='Render의 MODI_KIOSK_API_KEY와 같은 값'
python -m hardware.start_fixed_modi_p1
```

P1은 동부아파트입구에서 승차해 공업탑에서 내립니다. 이어서 Android에서 MODI 모드를 선택하고 P2를 `롯데마트`(모형의 롯데백화점 위치)에서 승차, `강남초등학교`에서 하차로 호출합니다. 두 호출이 모이면 서버는 다음 순서로 경유지를 확정합니다.

`동부아파트입구(P1 승차) → 롯데마트(P2 승차) → 강남초등학교(P2 하차) → 공업탑(P1 하차)`

이 고정 시나리오는 총 2개의 호출이 필요합니다. 한 호출의 동반 인원만으로는 출발하지 않습니다.

## 친구 파일 없이 직접 MODI 차량 실행

PyMODI+로 연결된 4개 모터와 IMU만 사용해 고정 경로를 실행할 수 있습니다. 차량 PC에 모형 지도를 놓고, 차량 앞을 지도에서 서쪽 방향으로 맞춘 뒤 실행합니다.

```bash
export BUS_EODIGA_VEHICLE_KEY='Render의 VEHICLE_API_KEY와 같은 값'
python -m hardware.fixed_modi_vehicle
```

이 드라이버는 서버가 `31208 → 64201 → 40410 → 40404` 네 정류장 순서를 보내지 않으면 모터를 구동하지 않습니다. 첫 시험은 차량을 들어 올린 상태에서 `MODI_DRIVE_SPEED=20`으로 실행하고, 정상 회전이 확인된 뒤 속도를 올립니다.

이 브리지는 Render의 공동 DRT 경유 순서를 받아 친구의 `MODI+ BLE + IMU V4` 자동차가 미니맵에서 같은 순서로 이동하게 합니다. 차량이 보고한 `EN_ROUTE`, `ARRIVED`, `BOARDED`, `DROPPED_OFF`, `COMPLETED` 상태는 Firestore를 통해 Android에 표시됩니다.

## 동부아파트입구 키오스크

`modi_station_kiosk.py`는 웹캠 카드 인식, 조이스틱 목적지 선택, 버튼 호출, 환경 센서 소음 감지와 디스플레이·LED·스피커를 담당합니다. 키오스크의 승차 정류장은 동부아파트입구로 고정되며 나머지 5개 정류장을 목적지로 선택합니다. Firestore에 직접 쓰지 않고 Render API를 호출하므로 Android의 MODI 호출과 같은 `modi-bus-01` 공동 배차열에 참여합니다.

카드 인식에는 친구가 학습한 `26swbest2.pt`가 필요합니다. 기본 위치는 `hardware/26swbest2.pt`이고 현재처럼 저장소 최상단에 둬도 자동으로 찾습니다. 다른 위치를 사용할 때는 `YOLO_MODEL_PATH`를 지정합니다. 확인된 현재 모델에는 `senior_card`, `disabled_card` 클래스가 모두 들어 있습니다.

Render에는 다음 값을 설정합니다.

```text
MODI_KIOSK_API_ENABLED=true
MODI_KIOSK_API_KEY=차량키와-다른-긴-비밀키
```

PC에서는 같은 키와 OpenAI 키를 환경변수로 전달합니다. OpenAI 키가 없으면 호출 기능은 작동하고 소음 이미지 AI 분석만 생략됩니다.

```bash
export BUS_EODIGA_KIOSK_KEY='Render와 같은 키'
export OPENAI_API_KEY='사용할 OpenAI 키'
export YOLO_MODEL_PATH='/친구에게/받은/26swbest2.pt'
python -m hardware.modi_station_kiosk
```

## 필요한 친구 파일

아래 파일은 현재 저장소에 없으므로 친구에게 받아 이 `hardware/` 폴더에 두어야 합니다.

- `modi_car_v4.py`: 전달받은 V4 코드는 이 폴더에 저장해 두었습니다.
- `car_route_v2.py`
- `modi_ble_connection.py`
- `turn_180_calibration.json`
- 친구의 미니맵 JSON: `nodes`와 `roads`가 포함되어야 함

V4 파일 이름이 다르면 `--controller-module`로 확장자를 제외한 모듈 이름을 지정합니다.

## Render 설정

하드웨어 시연 때만 Render 환경변수를 다음처럼 설정합니다.

```text
HARDWARE_VEHICLE_CONTROL_ENABLED=true
VEHICLE_API_KEY=충분히-긴-임의의-비밀키
```

이 모드에서는 Render 자동 운행이 중지되고 MODI 차량의 보고가 Android 진행 상태를 바꿉니다. MODI를 사용하지 않는 앱 시연에서는 `HARDWARE_VEHICLE_CONTROL_ENABLED=false`로 되돌립니다.

## 정류장과 미니맵 연결

Android의 `DemoPlaces.modiModelStops`와 같은 정류장 ID·좌표 6개만 사용하는 파일은 다음 명령으로 생성합니다.

```bash
python -m hardware.generate_six_stop_model --width-cm 120 --height-cm 80
```

- `six_stop_mini_map.json`: 위·경도 상대 배치를 120×80cm 모형 좌표로 투영한 6개 노드
- `modi_stop_mapping.json`: 정류장 ID와 `stop_1`~`stop_6` 대응
- `six_stop_combinations.json`: 같은 정류장을 제외한 방향 있는 출발–도착 30개 조합

차량의 물리 출발점은 항상 `stop_1 = 동부아파트입구(31208)`로 고정됩니다. 승객 조합은 30개를 유지하지만 차량은 매 운행 전에 동부아파트입구에서 출발하며, 이전 운행을 다른 정류장에서 끝냈다면 다음 운행 전에 동부아파트입구로 복귀합니다.

실제 모형 크기가 다르면 `--width-cm`, `--height-cm` 값을 바꿉니다. 생성 파일의 거리는 cm이므로 `car_route_v2.drive_distance`의 거리 단위·바퀴 보정값도 cm 기준인지 반드시 확인해야 합니다.

## 안전한 통신 시험

먼저 모터를 움직이지 않는 dry-run으로 시험합니다.

```bash
export BUS_EODIGA_VEHICLE_KEY='Render와 같은 비밀키'
python -m hardware.modi_backend_bridge --dry-run --once
```

## 실제 차량 실행

차량을 바닥에서 들어 올린 상태로 첫 시험을 진행하고, 비상시 `Ctrl+C`를 누릅니다. 종료 신호나 예외가 발생하면 네 바퀴 정지 명령을 전송합니다.

```bash
export BUS_EODIGA_VEHICLE_KEY='Render와 같은 비밀키'
python -m hardware.modi_backend_bridge \
  --hardware \
  --controller-module hardware.modi_car_v4 \
  --route-map hardware/six_stop_mini_map.json \
  --stop-mapping hardware/modi_stop_mapping.json
```
