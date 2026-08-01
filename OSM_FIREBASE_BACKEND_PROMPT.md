# BUS어디가 OSM·Firebase 백엔드 개발 프롬프트

너는 Python 교통 시스템과 공간정보 백엔드를 개발하는 시니어 엔지니어다. 기존 `drt_simulator` 프로젝트를 기반으로 울산광역시에서 운행할 다중 차량 DRT 백엔드를 구현하라.

## 서비스 설명

- Android 앱 이름은 `BUS어디가`다.
- 이용자는 Kotlin 앱에서 출발 위치, 목적지, 탑승 인원, 고령자·휠체어·시각·청각 지원 여부를 선택해 차량을 호출한다.
- 버스정류장 단말기도 카메라 카드 인식과 조이스틱 입력을 통해 같은 형식의 호출을 보낸다.
- 백엔드는 여러 차량의 위치와 정원을 고려해 요청을 묶고, 승차 전에 하차하지 않는 DARP/PDPTW 제약을 지키며 배차한다.
- 울산 124번, 134번, 순환11번 실제 노선과 같은 승객 요청으로 비교 시뮬레이션할 수 있어야 한다.
- Firebase는 인증, 호출 상태 저장, 실시간 UI 갱신, 보호자 알림에 사용한다.

## 중요한 설계 원칙

1. OpenStreetMap은 도로 데이터이며 그 자체가 경로 탐색 API는 아니다. 공개 OSM Tile/Nominatim/Overpass 서버를 상용 실시간 경로 계산에 남용하지 마라.
2. 개발 단계에서는 울산 영역 OSM 데이터를 내려받아 캐시한 NetworkX 기반 `OSMRouteProvider`를 사용할 수 있게 하라.
3. 운영 서버에서는 OSRM, Valhalla 또는 GraphHopper 중 하나를 Docker 서비스로 실행하고 `RouteProvider` 구현체로 감싸라. 1차 권장안은 자동차 경로가 단순한 OSRM이다.
4. 배차 알고리즘은 OSMnx, NetworkX, Firestore SDK를 직접 호출하지 않고 `RouteProvider`와 저장소 인터페이스만 사용해야 한다.
5. 좌표는 외부 API와 DB에서 WGS84 위도·경도(EPSG:4326)를 사용하고, 내부 거리 계산은 미터, 이동시간은 초로 통일한다.
6. Android 앱이 Firestore에 임의의 `ASSIGNED` 상태를 직접 쓰지 못하게 한다. 상태 변경 권한은 백엔드에 둔다.

## 권장 전체 구조

```text
Kotlin 앱 / 정류장 단말기
        │ HTTPS + Firebase ID Token 또는 Device Key
        ▼
FastAPI 백엔드
  ├─ 인증·요청 검증
  ├─ Ride Service
  ├─ Dispatch Service (DARP/PDPTW)
  ├─ RouteProvider
  ├─ Firebase Repository
  └─ 알림 Service
        │                │
        ▼                ▼
Firestore/RTDB/FCM    OSRM + Ulsan OSM data
```

## Firebase 역할

- Firebase Authentication: Android 사용자 로그인 및 ID Token 발급
- Firestore: 호출, 배차, 차량, 운행 결과처럼 보존할 데이터
- Realtime Database 또는 제한된 Firestore 기록: 차량의 고빈도 실시간 위치
- Firebase Cloud Messaging: 배차 완료, 차량 접근, 지연, 도착, 보호자 알림
- Firebase Admin SDK는 서버에서만 사용하고 서비스 계정 파일을 Git에 커밋하지 마라.
- 앱은 Firestore Snapshot Listener로 자신의 호출 상태를 관찰할 수 있지만, 상태 변경은 FastAPI를 통해 수행한다.

## Firestore 컬렉션 초안

### `ride_requests/{request_id}`

```json
{
  "user_id": "uid",
  "source": "ANDROID_APP",
  "pickup": {
    "place_id": "ulsan-station",
    "name": "울산역",
    "latitude": 35.5514,
    "longitude": 129.1387
  },
  "destination": {
    "place_id": "uh-hospital",
    "name": "울산대학교병원",
    "latitude": 35.5202,
    "longitude": 129.4284
  },
  "passenger_count": 1,
  "mobility_support": "WHEELCHAIR",
  "status": "WAITING",
  "assigned_vehicle_id": null,
  "created_at": "server timestamp",
  "updated_at": "server timestamp",
  "idempotency_key": "client-generated-uuid"
}
```

### `vehicles/{vehicle_id}`

- `status`: `OFFLINE`, `IDLE`, `TO_PICKUP`, `IN_SERVICE`, `RETURNING`
- `capacity`, `current_passengers`, `wheelchair_capacity`
- `current_location`, `last_location_at`
- `route_version`, `assigned_request_ids`

### `ride_events/{event_id}` 또는 호출 문서 하위 `events`

- `REQUESTED`, `ASSIGNED`, `VEHICLE_DEPARTED`, `PICKED_UP`, `DROPPED_OFF`, `CANCELLED`, `DELAYED`
- 서버 타임스탬프와 이전·새 상태를 기록해 발표와 장애 분석에 활용한다.

## 필수 API

- `GET /health`
- `GET /v1/places/search?query=&lat=&lon=`
- `POST /v1/routes/preview`
- `POST /v1/ride-requests` — 중복 방지를 위해 `Idempotency-Key` 지원
- `GET /v1/ride-requests/{request_id}`
- `POST /v1/ride-requests/{request_id}/cancel`
- `POST /v1/vehicles/{vehicle_id}/locations`
- `POST /v1/vehicles/{vehicle_id}/arrivals`
- `POST /v1/vehicles/{vehicle_id}/pickups/{request_id}`
- `POST /v1/vehicles/{vehicle_id}/dropoffs/{request_id}`

모든 사용자 API는 Firebase ID Token을 검증하고 문서의 `user_id`와 토큰 UID가 일치하는지 확인하라. 정류장 단말기와 차량 단말기는 별도의 제한된 장치 인증 방식을 사용하라.

## OSM 구현 요구사항

- 울산광역시 경계 또는 설정된 다각형 안의 운행 가능 도로를 준비한다.
- 입력 좌표를 가장 가까운 운행 가능 도로 노드에 스냅하되 스냅 거리 한도를 설정한다.
- 일방통행, 회전 가능 여부, 도로 등급, 제한속도 또는 도로 유형별 기본속도를 반영한다.
- 결과에 거리(m), 예상시간(s), 노드 경로와 화면 표시용 polyline을 포함한다.
- OSM 데이터 버전과 생성 날짜를 기록하고, 갱신 명령을 운영 배차 프로세스와 분리한다.
- 경로 결과는 좌표쌍과 프로필을 키로 짧게 캐시한다.
- 외부 지오코딩이 필요하면 Nominatim 사용 정책을 지키고 결과를 캐시한다. 운영 트래픽은 자체 인스턴스나 정식 제공자를 사용한다.

## 배차 알고리즘 요구사항

- 여러 차량을 지원한다.
- 각 후보 차량 경로에 새 `PICKUP`과 `DROPOFF`를 삽입해 증가 비용이 가장 작은 차량을 선택한다.
- 승차 선행, 정원, 휠체어석, 최대 대기시간, 최대 우회시간 제약을 검증한다.
- 비용은 총 이동시간, 대기시간 위반, 탑승 우회시간, 공차거리, 미배차 페널티를 각각 기록한다.
- 소규모 테스트는 제한된 완전탐색, 운영 기본은 삽입 휴리스틱/Greedy를 사용한다.
- 동일 요청이 중복 실행돼도 한 번만 배정되도록 Firestore Transaction 또는 분산 잠금을 사용한다.
- 여러 백엔드 워커가 동시에 같은 차량을 배정하지 못하도록 차량의 `route_version`을 이용한 낙관적 잠금을 구현한다.

## 실시간 위치와 알림

- 차량 GPS 업데이트는 3~10초 간격을 설정값으로 둔다.
- 오래된 위치는 `stale`로 처리하고 배차 대상에서 제외한다.
- 앱에는 모든 차량 위치가 아니라 사용자가 배정받은 차량과 필요한 경로만 공개한다.
- 배차 완료, 도착 임박, 지연, 승차, 도착 이벤트에서 FCM을 전송한다.
- 보호자 위치 공유는 사용자 동의, 만료 시간, 최소 공개 범위를 적용한다.

## 실제 버스 비교 시뮬레이션

- 기존 `route_11.csv`, `route_124.csv`, `route_134.csv`를 수정하지 말고 입력 어댑터로 읽는다.
- 실제 시간표 CSV가 추가되면 동일한 승객 요청을 고정노선과 DRT에 복제한다.
- OSMRouteProvider를 두 시뮬레이터가 공통 사용하도록 한다.
- 완료 승객, 미수송 승객, 평균/최대 대기시간, 승차시간, 총거리, 공차거리, 탑승률, 정시 수송률, 연료와 비용을 CSV로 저장한다.

## 구현 및 검증 순서

1. 기존 프로젝트와 테스트를 먼저 실행하고 구조를 설명한다.
2. `RouteProvider` 계약을 유지한 채 OSM 구현체를 추가한다.
3. 울산 소규모 영역에서 좌표 스냅과 최단 경로 테스트를 작성한다.
4. FastAPI 요청/응답 Pydantic 모델과 메모리 저장소로 API를 먼저 완성한다.
5. Firebase Emulator Suite를 사용하는 저장소 통합 테스트를 추가한다.
6. 다중 차량 삽입 배차와 동시성 테스트를 작성한다.
7. OSRM, FastAPI, Firebase Emulator를 실행할 Docker Compose 개발 환경을 제공한다.
8. 실제 Firebase 연결은 환경변수로 활성화하고 비밀키가 없을 때는 에뮬레이터 또는 메모리 모드로 실행되게 한다.
9. README에 macOS 설치법, OSM 데이터 준비법, 환경변수, API 실행법, 테스트법을 작성한다.

## 테스트 항목

- 울산 내부 좌표 사이의 실제 도로 경로 반환
- 운행 불가능한 위치와 연결되지 않은 도로 처리
- 승차 전 하차 금지와 차량 정원·휠체어석 검증
- 두 동시 요청이 한 차량 좌석을 중복 점유하지 않음
- 동일 Idempotency Key의 요청이 하나만 생성됨
- Firebase Token 누락·타 사용자 호출 접근 거부
- 차량 위치가 오래되면 배차 대상에서 제외
- 상태 전이가 `WAITING → ASSIGNED → PICKED_UP → COMPLETED` 순서를 지킴
- OSM 또는 Firebase가 일시적으로 실패할 때 재시도와 오류 상태 기록

## 완료 결과물

- 모듈화된 Python 소스와 타입 힌트·docstring
- FastAPI OpenAPI 문서
- OSM/OSRM RouteProvider 구현
- Firebase 저장소와 에뮬레이터 설정
- 다중 차량 DRT 배차 서비스
- Dockerfile 및 Docker Compose
- pytest 테스트
- Android 개발자가 사용할 API 요청·응답 예시
- 배포 및 비밀정보 관리 방법이 포함된 README

먼저 기존 파일을 덮어쓰지 말고 프로젝트를 분석한 뒤 설계, 변경 파일 목록, 데이터 흐름, 위험 요소를 제시하라. 그다음 작은 단계별로 구현하고 각 단계마다 테스트를 실행하라.
