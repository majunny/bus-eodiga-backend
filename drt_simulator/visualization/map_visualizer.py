"""Static Matplotlib map snapshots and experiment comparison charts."""

from pathlib import Path
from typing import Optional, Sequence

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
import pandas as pd  # noqa: E402

from map.route_provider import RouteProvider
from models import PassengerRequest, RequestStatus, StopTask, Vehicle


def _korean_font() -> FontProperties:
    """Return a Korean-capable macOS font with a portable fallback."""

    korean_font = Path("/System/Library/Fonts/AppleSDGothicNeo.ttc")
    return (FontProperties(fname=str(korean_font))
            if korean_font.exists() else FontProperties())


class MapVisualizer:
    """Render road, service state, planned routes, and metric comparisons."""

    _COLORS = {
        "DEPOT": "#4b5563",
        "SMART_STOP": "#2563eb",
        "DESTINATION": "#dc2626",
        "INTERSECTION": "#9ca3af",
    }
    _NODE_TYPE_LABELS = {
        "DEPOT": "차고지",
        "SMART_STOP": "스마트 정류장",
        "DESTINATION": "주요 목적지",
        "INTERSECTION": "교차로",
    }

    def __init__(self, routes: RouteProvider) -> None:
        """Store only the public route-provider interface."""

        self.routes = routes
        self.label_font = _korean_font()

    def plot_map(self, output_path: Path, vehicle: Optional[Vehicle] = None,
                 requests: Sequence[PassengerRequest] = (),
                 planned_route: Sequence[StopTask] = ()) -> Path:
        """Save a static road-network and current-service snapshot."""

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        nodes = {item["node_id"]: item for item in self.routes.get_all_locations()}
        figure, axis = plt.subplots(figsize=(11, 8))
        for road in self.routes.get_road_segments():
            start = nodes[road["start"]]
            end = nodes[road["end"]]
            axis.plot([start["x"], end["x"]], [start["y"], end["y"]],
                      color="#cbd5e1", linewidth=1.5, zorder=1)
        for node_type, color in self._COLORS.items():
            selected = [node for node in nodes.values()
                        if node["node_type"] == node_type]
            if selected:
                axis.scatter([node["x"] for node in selected],
                             [node["y"] for node in selected],
                             color=color, s=70 if node_type != "INTERSECTION" else 25,
                             label=self._NODE_TYPE_LABELS[node_type], zorder=3)
        for node in nodes.values():
            if node["node_type"] != "INTERSECTION":
                axis.annotate(node["name"], (node["x"], node["y"]),
                              xytext=(5, 6), textcoords="offset points", fontsize=9,
                              fontproperties=self.label_font)
        waiting = [request for request in requests
                   if request.status == RequestStatus.WAITING]
        for index, request in enumerate(waiting):
            origin = nodes[request.origin]
            axis.scatter(origin["x"], origin["y"], marker="o", facecolors="none",
                         edgecolors="#f59e0b", s=150, linewidth=2, zorder=4,
                         label="대기 요청" if index == 0 else None)
        if planned_route:
            route_nodes = ([vehicle.current_node] if vehicle else []) + [
                task.node_id for task in planned_route
            ]
            coordinates = [nodes[node_id] for node_id in route_nodes]
            axis.plot([item["x"] for item in coordinates],
                      [item["y"] for item in coordinates],
                      color="#7c3aed", linestyle="--", linewidth=2.5,
                      label="현재 계획 경로", zorder=2)
        if vehicle:
            current = nodes[vehicle.current_node]
            axis.scatter(current["x"], current["y"], marker="s", color="#16a34a",
                         edgecolor="black", s=180, label="버스 탑승 인원 ({}/{})".format(
                             vehicle.current_passengers, vehicle.capacity), zorder=5)
        axis.set_title("하이브리드 DRT 가상 도로망", fontproperties=self.label_font,
                       fontsize=16)
        axis.set_xlabel("가상 동서 좌표", fontproperties=self.label_font)
        axis.set_ylabel("가상 남북 좌표", fontproperties=self.label_font)
        axis.set_aspect("equal", adjustable="box")
        axis.grid(alpha=0.2)
        axis.legend(loc="best", prop=self.label_font)
        figure.tight_layout()
        figure.savefig(str(output_path), dpi=160)
        plt.close(figure)
        return output_path

    @staticmethod
    def plot_comparison(frame: pd.DataFrame, output_path: Path) -> Path:
        """Save five service and efficiency comparisons by system type."""

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        korean_font = _korean_font()
        metrics = [
            ("average_wait_time", "평균 대기시간 (분)"),
            ("total_distance", "총 운행거리 (km)"),
            ("empty_distance", "공차 운행거리 (km)"),
            ("missed_passengers", "미수송 승객 수 (명)"),
            ("average_occupancy", "평균 탑승률"),
        ]
        averages = frame.groupby("system_type")[[item[0] for item in metrics]].mean()
        order = [item for item in ("FIXED_ROUTE", "DRT") if item in averages.index]
        averages = averages.loc[order]
        averages.index = [
            "기존 고정노선" if item == "FIXED_ROUTE" else "수요응답형 DRT"
            for item in order
        ]
        figure, axes = plt.subplots(2, 3, figsize=(14, 8))
        colors = ["#64748b", "#2563eb"]
        for axis, (column, title) in zip(axes.flat, metrics):
            averages[column].plot(kind="bar", ax=axis, color=colors)
            axis.set_title(title, fontproperties=korean_font)
            axis.set_xlabel("")
            axis.tick_params(axis="x", rotation=0)
            for label in axis.get_xticklabels():
                label.set_fontproperties(korean_font)
            axis.grid(axis="y", alpha=0.25)
        axes.flat[-1].axis("off")
        figure.suptitle("기존 고정노선과 DRT 비교", fontsize=16,
                        fontproperties=korean_font)
        figure.tight_layout()
        figure.savefig(str(output_path), dpi=160)
        plt.close(figure)
        return output_path
