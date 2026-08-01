# 울산 버스 CSV 입력 규칙

## 노선 파일

파일명은 `route_<노선번호>.csv`이며 다음 컬럼을 사용한다.

```csv
direction,stop_sequence,stop_id,stop_name
```

- `direction`: 방면 또는 순환 운행 구분
- `stop_sequence`: 방문 순번, 1부터 연속 증가
- `stop_id`: 울산 BIS 정류장 ID, 문자열로 취급
- `stop_name`: 화면에 표시되는 정류장명

## 시간표 파일

파일명은 `timetable_<노선번호>.csv`이며 다음 컬럼을 사용한다.

```csv
route_number,day_type,direction,origin,departure_time,service_variant
```

- 한 출발시각당 한 행
- `day_type`: `평일`, `토요일`, `공휴일`
- `departure_time`: 24시간제 `HH:MM`
- `service_variant`: 기본 운행은 `기본`, 지원·단축 운행은 해당 명칭
- 엑셀에서 `CSV UTF-8`로 저장

## 정류장 좌표 파일

`stops_ulsan.csv`는 최소 다음 컬럼을 사용한다.

```csv
stop_id,stop_name,latitude,longitude
```

노선 파일의 `stop_id`와 좌표 파일의 `stop_id`를 결합 키로 사용한다.

