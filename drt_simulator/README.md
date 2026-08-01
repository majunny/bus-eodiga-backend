# AI 기반 하이브리드 DRT 버스 시뮬레이터

교통 취약지역과 고령자 이동을 가정한 오프라인 Python 교통 시뮬레이터입니다. 스마트 정류장 카메라 카드 또는 Android 앱에서 들어올 미래 호출을 `PassengerRequest`로 통합할 수 있도록 설계했으며, 현재 버전은 외부 서비스나 하드웨어 없이 좌표 기반 가상 도로망에서 고정노선과 호출형 DRT를 비교합니다.

## 1차 구현 범위

- 차량 1대(모델과 결과 구조는 다차량 확장 가능)
- 스마트 정류장 2개, 병원·시장·복지관·행정복지센터 4개, 교차로 10개
- JSON 편집형 방향 도로망과 NetworkX 최단시간 경로
- 재현 가능한 5개 수요 시나리오
- 요청 상태 검증, 출발 정책, 정규화 우선순위
- pickup-before-dropoff 및 차량 정원 제약 경로 최적화
- 제한 완전탐색(`BRUTE_FORCE`)과 최근접 기반 휴리스틱(`GREEDY`)
- 운행 중 요청의 비용 제한 삽입
- 동일 요청 복사본을 사용하는 고정노선/DRT 비교
- 서비스 품질·거리·연료·비용 지표, CSV, 비교 그래프
- pytest 핵심 알고리즘/통합 테스트

Firebase, YOLO, Kotlin, MODI 코드는 아직 포함하지 않습니다. 향후 호출 채널은 `RequestSource`, 지도 교체는 `BaseMap`/`RouteProvider` 경계에 연결합니다.

## 설계

### 핵심 책임

| 영역 | 주요 객체 | 책임 |
|---|---|---|
| 설정/모델 | `SimulationConfig`, `PassengerRequest`, `Vehicle`, `StopTask` | 단위·임계값·상태를 한곳에서 정의 |
| 지도 | `BaseMap`, `VirtualMap`, `RouteProvider` | JSON 도로망 로드와 거리·시간·경로 API 제공 |
| 요청 | `PassengerGenerator`, `RequestManager` | 시드 기반 생성, 중복 방지, 상태 전이, 그룹화 |
| 알고리즘 | `DeparturePolicy`, `DispatchStrategy`, `RouteOptimizer` | 출발 이유, 우선순위, 제약 경로 계산 |
| 시뮬레이션 | `DRTSimulator`, `FixedRouteSimulator` | 요청 도착·이동·승하차·복귀 이벤트 진행 |
| 평가 | `MetricsCalculator`, `ExperimentRunner` | 공통 지표, paired experiment, CSV/통계 |
| 표현 | `MapVisualizer` | 지도 스냅샷과 비교 차트 |

데이터 흐름은 다음과 같습니다.

```text
virtual_map.json -> VirtualMap -> RouteProvider
                                  |
seed/scenario -> PassengerGenerator -> 원본 요청
                                      | deep copy
                         +------------+------------+
                         |                         |
                  FixedRouteSimulator         DRTSimulator
                         |                         |
                         +---- SimulationResult --+
                                      |
                         Metrics -> CSV/summary/PNG
```

배차와 최적화 코드는 NetworkX 그래프나 좌표를 직접 사용하지 않고 `RouteProvider`의 `get_distance`, `get_travel_time`, `get_shortest_path`, `get_node`, `get_all_locations`만 사용합니다. 따라서 나중에 같은 계약을 구현한 `OSMMap`을 주입하면 알고리즘을 수정하지 않아도 됩니다. `get_road_segments`는 시각화용 추가 API입니다.

## 알고리즘 선택

시뮬레이션은 **1분 고정 시간 간격 방식**입니다. 고교 대회 시연에서 요청 도착과 차량 상태를 단계별로 설명하기 쉽고, 운행 중 새 요청을 정류장 도착 시점에 안전하게 삽입하기 쉽기 때문입니다. 도로 구간의 실제 이동시간은 `distance_km / speed_kmh * 60 * congestion_factor`로 실수 분 단위 계산하여 거리·비용 지표에는 반올림 손실 없이 반영합니다.

경로 최적화는 단순 TSP가 아닙니다.

- `BRUTE_FORCE`: feasible action만 확장하는 backtracking입니다. 승차 선행, 정원, 탑승객 목적지 방문을 탐색 중 검증하고 작은 요청에서 최적 비용을 찾습니다.
- `GREEDY`: 현재 위치에서 가까운 feasible task를 고르되 최대 대기시간에 가까운 pickup에 urgency를 줍니다.
- 작업 수가 `brute_force_max_tasks`(기본 8)를 넘으면 조합 폭증을 막기 위해 자동으로 greedy를 사용합니다.

경로 비용은 이동시간, 최대 대기 초과, 직접 이동 대비 추가 탑승시간, 미처리 승객, 공차거리 항목을 별도로 기록한 후 `RouteCostWeights`로 결합합니다. 요청 우선순위는 대기시간/최대대기시간, 승객수/정원, 목적지 그룹수/최대그룹수, 차량거리/후보 최대거리로 무차원 정규화합니다. 최대 대기의 80%를 넘으면 거리와 무관하게 urgency bonus가 빠르게 증가합니다.

운행 중 요청 삽입은 차량이 도로 중간에 있을 때가 아니라 다음 정류장에 도착했을 때 평가합니다. 기존 계획과 새 요청 포함 계획의 이동시간 증가가 `dynamic_insertion_max_cost_minutes` 이하일 때만 경로를 교체합니다.

## 프로젝트 구조

```text
drt_simulator/
├── main.py, config.py, models.py
├── map/
│   ├── base_map.py, virtual_map.py, route_provider.py
├── algorithms/
│   ├── request_manager.py, departure_policy.py
│   ├── dispatch.py, route_optimizer.py
├── simulation/
│   ├── passenger_generator.py, drt_simulator.py
│   ├── fixed_route_simulator.py, metrics.py, experiment_runner.py
├── visualization/map_visualizer.py
├── data/
│   ├── virtual_map.json
│   └── simulation_results/
└── tests/
```

Python 패키지는 표준 관례인 `__init__.py`를 사용합니다. 제안 구조의 `init.py`보다 import 도구·pytest·IDE가 패키지를 정확하게 인식합니다. 반복 실험 책임이 시뮬레이터와 다르므로 `simulation/experiment_runner.py`도 추가했습니다.

## 설치

macOS와 Python 3.8.10을 기준으로 작성했습니다.

```bash
cd drt_simulator
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

설치 후 인터넷 없이 실행할 수 있습니다. 프로젝트 코드에는 지도 API나 외부 서비스 호출이 없습니다.

## 실행

```bash
python main.py --mode demo
python main.py --mode demo --optimizer brute_force
python main.py --mode demo --optimizer greedy

python main.py --mode compare --runs 100
python main.py --mode compare --runs 1000 --scenario low_demand
```

추가 옵션은 `--seed`, `--duration`, `--scenario`입니다. 시나리오는 `low_demand`, `normal_demand`, `peak_demand`, `destination_concentrated`, `random_scattered`를 지원합니다.

결과는 `data/simulation_results/`에 저장됩니다.

- 원시 paired experiment CSV
- 평균/중앙값/표준편차 summary CSV
- 평균 대기시간, 총거리, 공차거리, 미수송 승객, 평균 탑승률 비교 PNG
- demo 지도 PNG

## 지도 편집

`data/virtual_map.json`의 `nodes`와 `roads`를 직접 수정합니다. 거리 km, 속도 km/h, 시간 minute를 프로젝트 전체에서 사용합니다.

노드 필드:

```json
{
  "node_id": "hospital",
  "name": "병원",
  "x": 8.5,
  "y": 7.5,
  "node_type": "DESTINATION",
  "passenger_demand_weight": 1.8
}
```

도로 필드:

```json
{
  "start": "j8",
  "end": "hospital",
  "distance_km": 1.0,
  "speed_limit_kmh": 35,
  "congestion_factor": 1.1,
  "one_way": false,
  "is_open": true
}
```

파일이 없으면 `VirtualMap`이 동일한 기본 예제 지도를 자동 생성합니다. 닫힌 도로는 그래프에 넣지 않으며, 일방통행이 아니면 역방향 간선도 생성합니다.

## 설정

대부분의 실험값은 `config.py`의 dataclass에서 변경합니다.

- 차량 정원 6명
- 최소 출발 3명
- 최대 대기 10분
- 동일 목적지 기준 2명
- 배차간격 20분
- 동적 삽입 허용 및 최대 증가시간
- 수요율/목적지 확률(병원 40%, 복지관 30% 기본)
- 우선순위/경로비용 가중치
- 연비, 연료가격, 시간비용, 미수송 비용

## 테스트

```bash
pytest -q
```

최단경로, 단절 노드, 출발 임계값, 승하차 선행관계, 정원, 시드 재현성, 동일 입력, 완료 요청 대기시간, CSV 생성을 검사합니다.

## 알려진 1차 버전 한계와 확장 방향

- 실제 교통 데이터 대신 정적 혼잡계수를 사용합니다.
- 차량 위치는 도로 링크 내부 GPS 좌표가 아니라 시간에 따른 링크 이동 상태와 도착 노드로 표현합니다.
- 완전탐색은 작은 요청 묶음 전용입니다. 다차량/대규모에서는 insertion heuristic, OR-Tools 또는 rolling horizon이 필요합니다.
- 한 차량을 기본 실행하지만 `Vehicle` 목록과 `SimulationResult.vehicles`는 fleet 확장을 허용합니다. 다음 단계에서는 차량 선택 비용을 분리한 dispatcher가 필요합니다.
- OSM 연동 시 `BaseMap` 계약을 구현하고 `RouteProvider(VirtualMap(...))` 주입부만 교체합니다.

