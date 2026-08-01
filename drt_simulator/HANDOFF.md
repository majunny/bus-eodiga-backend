# 울산 실제 노선 비교 시뮬레이션 인수인계

## 전달 목적

현재 Python DRT 시뮬레이터를 기반으로 울산 124번·134번·순환11번 실제 고정노선과 다차량 DRT를 동일 승객 요청으로 비교한다.

## 현재 완료된 기능

- JSON 기반 가상 도로망과 `RouteProvider` 추상화
- 고정노선 및 차량 1대 DRT 시뮬레이션
- 출발 정책, 요청 우선순위, 승하차 제약 경로 최적화
- 반복 실험, CSV 지표, 한국어 지도 및 비교 그래프
- pytest 핵심 테스트 10개
- 울산 노선 정류장 목록 CSV 3개

## 현재 노선 CSV 상태

| 파일 | 상태 | 내용 |
|---|---|---|
| `buscsv/route_11.csv` | 완료 | 명촌차고지 출발·복귀, 45개 정류장 |
| `buscsv/route_124.csv` | 완료 | 율리 출발, 지웰시티자이 회차, 율리 복귀, 89개 정류장 |
| `buscsv/route_134.csv` | 부분 완료 | 꽃바위→율리 한 방향, 67개 정류장 |

`route_134.csv`에는 율리→꽃바위 반대 방향이 없다. 실제 운행을 왕복으로 비교하려면 반대 방향 정류장 목록을 별도 수집하거나 하나의 왕복 목록으로 결합해야 한다.

## 아직 필요한 데이터

1. `timetable_11.csv`, `timetable_124.csv`, `timetable_134.csv`
2. 울산 정류장 ID·이름·위도·경도가 있는 `stops_ulsan.csv`
3. 실제 운행 차량 수 또는 비교에 사용할 동일 차량 수 가정
4. 평일·토요일·공휴일 중 실험 기준일 선택

시간표는 `buscsv/timetable_template.csv`의 컬럼을 사용한다. 한 출발시각당 한 행으로 저장하고 CSV UTF-8로 내보낸다.

## 중요한 현재 한계

현재 `simulation/fixed_route_simulator.py`는 `config.py`의 가상 노드를 사용하는 예제 구현이다. `buscsv`의 울산 실제 노선은 아직 자동으로 읽히지 않는다. OSM 지도도 아직 구현되지 않았으므로 현재 `python main.py --mode demo`는 가상 지도 데모를 실행한다.

## 권장 다음 구현 순서

1. `UlsanRouteLoader`를 만들어 노선·시간표·정류장 좌표 CSV 검증 및 로드
2. 노선별 정류장 ID에 위도·경도 결합
3. OSMnx로 세 노선 주변 차량 도로망을 다운로드하고 GraphML로 캐시
4. `OSMMap(BaseMap)`을 구현해 위·경도를 가장 가까운 차량 도로 노드에 스냅
5. `ActualFixedRouteSimulator`에서 실제 정류장 순서와 출발시각 사용
6. `FleetDispatcher`를 추가해 DRT 차량 여러 대 지원
7. 동일 승객 요청, 동일 차량 수, 동일 실험시간으로 고정노선과 DRT 비교
8. 원시 결과와 가정값을 함께 CSV에 기록

## 공정한 비교 조건

- 두 시스템에 동일한 원본 승객 요청을 deep copy하여 제공한다.
- 총 차량 수, 차량 정원, 실험시간, 도로 이동시간 모델을 동일하게 한다.
- 고정노선은 실제 시간표와 정류장 순서를 사용한다.
- DRT는 같은 운행 영역과 차고지를 사용한다.
- 실제 승객 수요 데이터가 없으면 수요가 합성 데이터임을 결과에 명시한다.

## 설치와 확인

```bash
cd drt_simulator
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python main.py --mode demo
```

`pytest` 실행 파일이 다른 Python을 가리킬 수 있으므로 반드시 `python -m pytest` 형식을 사용한다.

## 주요 파일

- `config.py`: 차량·출발·비용·수요 설정
- `models.py`: 요청·차량·정류 작업·결과 모델
- `map/base_map.py`: OSM 구현이 따라야 할 지도 인터페이스
- `algorithms/route_optimizer.py`: 승차 선행·정원 제약 경로 최적화
- `simulation/fixed_route_simulator.py`: 현재 가상 고정노선 기준선
- `simulation/drt_simulator.py`: 현재 차량 1대 DRT 엔진
- `simulation/experiment_runner.py`: 동일 요청 반복 비교
- `visualization/map_visualizer.py`: 한국어 지도·결과 그래프

