"""제공된 버스 정류장 좌표 6개를 OpenStreetMap 위에 표시합니다.

실행:
    python visualization/osm_bus_stop_map.py
    python visualization/osm_bus_stop_map.py --output bus_stops.html

별도 Python 패키지 없이 Leaflet 기반 HTML 파일을 생성합니다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BUS_STOPS = [
    {
        "name": "동부아파트입구",
        "latitude": 35.52742029,
        "longitude": 129.3225519,
        "department": "버스택시과",
        "stop_id": "31208",
        "region": "울산광역시 남구",
    },
    {
        "name": "수암시장앞",
        "latitude": 35.52792702,
        "longitude": 129.3207326,
        "department": "버스택시과",
        "stop_id": "31205",
        "region": "울산광역시 남구",
    },
    {
        "name": "공업탑",
        "latitude": 35.53301001,
        "longitude": 129.3097744,
        "department": "버스택시과",
        "stop_id": "40404",
        "region": "울산광역시 남구",
    },
    {
        "name": "달동현대아파트앞",
        "latitude": 35.53630572,
        "longitude": 129.3237411,
        "department": "버스택시과",
        "stop_id": "40411",
        "region": "울산광역시 남구",
    },
    {
        "name": "강남초등학교",
        "latitude": 35.5358198,
        "longitude": 129.3205483,
        "department": "버스택시과",
        "stop_id": "40410",
        "region": "울산광역시 남구",
    },
    {
        "name": "롯데마트",
        "latitude": 35.23916902,
        "longitude": 129.0927024,
        "department": "버스운영과",
        "stop_id": "57172",
        "region": "부산광역시",
    },
]


HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>버스 정류장 OSM 지도</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{ width: 100%; height: 100%; margin: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Noto Sans KR", sans-serif; }}
    .number-marker {{
      width: 34px; height: 34px; border: 3px solid white; border-radius: 50%;
      color: white; font-weight: 800; font-size: 16px; line-height: 34px;
      text-align: center; box-shadow: 0 2px 8px rgba(0,0,0,.35);
    }}
    .ulsan {{ background: #0767c8; }}
    .busan {{ background: #ef6c00; }}
    .legend {{
      background: rgba(255,255,255,.94); padding: 12px 14px; border-radius: 10px;
      box-shadow: 0 2px 10px rgba(0,0,0,.22); line-height: 1.55;
    }}
    .legend strong {{ display: block; margin-bottom: 4px; }}
    .dot {{ display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const stops = {stops_json};
    const map = L.map('map');
    L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }}).addTo(map);

    const bounds = [];
    stops.forEach((stop, index) => {{
      const isBusan = stop.region.startsWith('부산');
      const icon = L.divIcon({{
        className: '',
        html: `<div class="number-marker ${{isBusan ? 'busan' : 'ulsan'}}">${{index + 1}}</div>`,
        iconSize: [40, 40],
        iconAnchor: [20, 20],
        popupAnchor: [0, -22]
      }});
      const marker = L.marker([stop.latitude, stop.longitude], {{icon}}).addTo(map);
      marker.bindTooltip(`${{index + 1}}. ${{stop.name}}`, {{direction: 'top', offset: [0, -18]}});
      marker.bindPopup(`
        <b>${{index + 1}}. ${{stop.name}}</b><br>
        정류장 ID: ${{stop.stop_id}}<br>
        ${{stop.region}} · ${{stop.department}}<br>
        ${{stop.latitude}}, ${{stop.longitude}}
      `);
      bounds.push([stop.latitude, stop.longitude]);
    }});
    map.fitBounds(bounds, {{padding: [55, 55]}});

    const legend = L.control({{position: 'topright'}});
    legend.onAdd = () => {{
      const div = L.DomUtil.create('div', 'legend');
      div.innerHTML = '<strong>버스 정류장 6곳</strong>' +
        '<span class="dot" style="background:#0767c8"></span>울산 5곳<br>' +
        '<span class="dot" style="background:#ef6c00"></span>부산 1곳';
      return div;
    }};
    legend.addTo(map);
  </script>
</body>
</html>
"""


def create_map(output_path: Path) -> Path:
    """정류장 데이터가 포함된 단일 HTML 지도를 생성합니다."""

    html = HTML_TEMPLATE.format(stops_json=json.dumps(BUS_STOPS, ensure_ascii=False))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="버스 정류장 6곳을 OSM 위에 표시합니다.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("osm_bus_stops.html"),
        help="생성할 HTML 경로 (기본값: osm_bus_stops.html)",
    )
    args = parser.parse_args()
    output = create_map(args.output)
    print(f"OSM 지도를 생성했습니다: {output}")


if __name__ == "__main__":
    main()
