# BUS어디가 백엔드

Kotlin 앱의 호출을 받고 Firebase Authentication 토큰을 검증한 뒤 Firestore에 저장하는 Render용 FastAPI 서버입니다. 호출 생성·조회·취소 API와 메모리/Firestore 저장소, OSRM을 이용한 OpenStreetMap 도로 경로 미리보기가 구현되어 있습니다. 실제 배차 서비스는 `RideRepository`와 분리해서 다음 단계에 연결합니다.

## 로컬 실행

백엔드는 Firebase Admin SDK 지원 기간을 고려해 Python 3.11 이상을 권장합니다.

```bash
cd drt_simulator
python3.11 -m venv .venv-backend
source .venv-backend/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example .env
uvicorn backend.main:app --reload
```

개발 모드에서는 `.env`의 `ALLOW_DEV_AUTH=true`와 `DEV_AUTH_TOKEN`을 사용합니다. 운영 환경에서는 반드시 `ALLOW_DEV_AUTH=false`여야 합니다.

확인 주소:

- 상태: `http://127.0.0.1:8000/health`
- API 문서: `http://127.0.0.1:8000/docs`

## OSM 경로 예제

`/api/find_nearest`는 Android 경로 미리보기에서 인증 없이 호출하며, 후보 중 도로 거리가 가장 짧은 목적지와 `[위도, 경도]` 순서의 경로 좌표를 반환합니다.

```bash
curl -X POST http://127.0.0.1:8000/api/find_nearest \
  -H "Content-Type: application/json" \
  -d '{
    "start_lat": 35.5514,
    "start_lon": 129.1387,
    "hospitals": [
      {"name": "울산대학교병원", "lat": 35.5202, "lon": 129.4284}
    ],
    "network_type": "drive",
    "buffer_m": 1200
  }'
```

기본 라우팅 서버는 `https://router.project-osrm.org`이며 `OSRM_BASE_URL` 환경변수로 자체 OSRM 서버를 지정할 수 있습니다. `ROUTING_TIMEOUT_SECONDS`로 외부 요청 제한 시간을 설정합니다.

## 울산 정류소 API

`backend/data/ulsan_bus_stops_20260522.csv`는 울산광역시가 제공한 `울산광역시_버스 정류소 위치 정보_20260522.CSV`를 UTF-8로 변환한 원본입니다. 전체 행 중 권역이 울산광역시 5개 구·군인 정류소 3,616개를 서버 시작 시 한 번 적재합니다.

- 이름 검색: `GET /v1/bus-stops?query=태화강역&limit=30`
- 주변 검색: `GET /v1/bus-stops/nearby?latitude=35.53937&longitude=129.35194&radius_m=2000&limit=30`

주변 검색 결과는 직선거리 `distance_m` 오름차순이며, Android는 GPS 위치에서 가장 가까운 실제 정류장을 탑승지로 사용합니다.

## 호출 예제

```bash
curl -X POST http://127.0.0.1:8000/v1/ride-requests \
  -H "Authorization: Bearer replace-this-local-token" \
  -H "Idempotency-Key: demo-request-0001" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "ANDROID_APP",
    "pickup": {
      "place_id": "ulsan-station",
      "name": "울산역",
      "location": {"latitude": 35.5514, "longitude": 129.1387}
    },
    "destination": {
      "place_id": "uh-hospital",
      "name": "울산대학교병원",
      "location": {"latitude": 35.5202, "longitude": 129.4284}
    },
    "passenger_count": 1,
    "mobility_support": "SENIOR"
  }'
```

## Render 설정

저장소 루트의 `render.yaml`을 Blueprint로 불러옵니다. Render 환경변수에는 다음 값을 넣습니다.

- `FIREBASE_PROJECT_ID`: Firebase 프로젝트 ID
- `FIREBASE_CREDENTIALS_JSON`: Firebase 서비스 계정 JSON 전체 내용(Secret)
- `STORE_BACKEND=firestore`
- `ALLOW_DEV_AUTH=false`
- `OSRM_BASE_URL=https://router.project-osrm.org` (선택)

Build Command와 Start Command는 `render.yaml`에 정의되어 있습니다. Health Check Path는 `/health`입니다.

서비스 계정 JSON 파일은 저장소에 올리지 않습니다. Render Secret 환경변수로만 보관합니다.

## 인증 흐름

1. Android가 Firebase Authentication으로 로그인합니다.
2. Android가 현재 사용자의 Firebase ID Token을 가져옵니다.
3. `Authorization: Bearer <ID_TOKEN>`으로 Render API를 호출합니다.
4. 서버가 Firebase Admin SDK로 토큰을 검증하고 UID를 읽습니다.
5. 서버가 해당 UID를 `ride_requests.user_id`로 저장합니다.
6. Android는 본인 호출 문서만 Firestore Snapshot Listener로 읽습니다.

## 테스트

```bash
cd drt_simulator
python -m pytest backend/tests -q
```
