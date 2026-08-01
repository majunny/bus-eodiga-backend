# -*- coding: utf-8 -*-
"""MODI+ BLE + IMU 피드백을 사용하는 4륜 자동차 경로 제어 V4.

친구가 제공한 제어 코드를 백엔드 브리지에서 import할 수 있도록 저장한 파일입니다.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import car_route_v2
from modi_ble_connection import connect_ble


TURN_SPEED_FAST = 55
TURN_SPEED_SLOW = 35
SLOW_DOWN_REMAINING_DEG = 25.0
STOP_BEFORE_TARGET_DEG = 4.0
MIN_TURN_DEG = 2.0
GYRO_POLL_SECONDS = 0.02
GYRO_WARMUP_SECONDS = 1.0
GYRO_STALE_TIMEOUT_SECONDS = 1.0
MAX_TURN_SECONDS = 20.0

_imu = None
_reference_imu_yaw = None
_wheels = {}
_turn_seconds_180 = None

FRONT_LEFT_INDEX = 2
FRONT_RIGHT_INDEX = 0
REAR_LEFT_INDEX = 1
REAR_RIGHT_INDEX = 3

CALIBRATION_HEADING_DEG = 180.0
MOTOR_SIGN_FOR_POSITIVE_YAW = -1
ABSOLUTE_HEADING_TOLERANCE_DEG = 4.0
HEADING_SETTLE_SECONDS = 0.30
MAX_HEADING_CORRECTIONS = 30
MAX_ABSOLUTE_TURN_SECONDS = 30.0
HEADING_PULSE_SPEED = 25
HEADING_FAST_PULSE_SPEED = 40
HEADING_DEGREES_PER_PULSE = 15.0
HEADING_PULSE_MIN_SECONDS = 0.03
HEADING_PULSE_MAX_SECONDS = 5.0
TURN_CALIBRATION_PATH = Path(__file__).with_name("turn_180_calibration.json")


def connect_ble_with_imu():
    """Bluetooth로 연결하고 V4 회전에 사용할 모터와 IMU를 보관한다."""
    global _imu, _reference_imu_yaw, _wheels

    bundle = connect_ble()
    if len(bundle.motors) < 4:
        raise RuntimeError(f"4륜 구동에는 모터 4개가 필요합니다. 현재 {len(bundle.motors)}개 연결됨")

    _wheels = {
        "front_left": bundle.motors[FRONT_LEFT_INDEX],
        "front_right": bundle.motors[FRONT_RIGHT_INDEX],
        "rear_left": bundle.motors[REAR_LEFT_INDEX],
        "rear_right": bundle.motors[REAR_RIGHT_INDEX],
    }
    print("4륜 모터 배치:")
    print(f"  앞 왼쪽  = 인덱스 {FRONT_LEFT_INDEX}, ID {_wheels['front_left'].id}")
    print(f"  앞 오른쪽= 인덱스 {FRONT_RIGHT_INDEX}, ID {_wheels['front_right'].id}")
    print(f"  뒤 왼쪽  = 인덱스 {REAR_LEFT_INDEX}, ID {_wheels['rear_left'].id}")
    print(f"  뒤 오른쪽= 인덱스 {REAR_RIGHT_INDEX}, ID {_wheels['rear_right'].id}")

    if not bundle.imus:
        raise RuntimeError("MODI+ IMU(자이로) 모듈이 없습니다. IMU를 연결한 뒤 다시 실행하세요.")
    _imu = bundle.imus[0]
    print(f"IMU 연결됨 (모듈 ID: {_imu.id})")
    print(f"자이로 안정화 대기: {GYRO_WARMUP_SECONDS:.1f}초")
    time.sleep(GYRO_WARMUP_SECONDS)

    first_yaw = float(_imu.angle_z)
    if not math.isfinite(first_yaw):
        raise RuntimeError("IMU angle_z 값이 올바르지 않습니다.")
    print(f"초기 yaw: {first_yaw:.1f}°")
    print("자동차 앞을 현실의 '서쪽'으로 정확히 맞춰 주세요.")
    input("방향을 맞춘 뒤 Enter를 누르면 서쪽(180°) 기준을 저장합니다: ")
    _reference_imu_yaw = float(_imu.angle_z)
    print(
        f"방향 기준 저장: IMU {_reference_imu_yaw:.1f}° "
        f"= 현실 방위 {CALIBRATION_HEADING_DEG:.1f}°(서쪽)"
    )
    return bundle


def set_four_wheel_speeds(
    unused_left_motor, unused_right_motor, left_speed: int, right_speed: int
) -> None:
    """좌우 네 바퀴에 속도 명령을 전송한다."""
    del unused_left_motor, unused_right_motor
    if len(_wheels) != 4:
        raise RuntimeError("4륜 모터가 초기화되지 않았습니다.")
    _wheels["front_left"].speed = left_speed
    _wheels["front_right"].speed = right_speed
    _wheels["rear_left"].speed = left_speed
    _wheels["rear_right"].speed = right_speed


def stop_four_wheels(unused_left_motor, unused_right_motor) -> None:
    """speed=0과 전용 stop을 반복 전송하여 네 바퀴를 강제 정지한다."""
    del unused_left_motor, unused_right_motor
    if len(_wheels) != 4:
        return
    stop_order = ("front_right", "front_left", "rear_right", "rear_left")
    for _ in range(3):
        for wheel_name in stop_order:
            _wheels[wheel_name].speed = 0
        for wheel_name in stop_order:
            _wheels[wheel_name].stop()
        time.sleep(0.08)


def wrapped_delta(current: float, previous: float) -> float:
    return (current - previous + 180.0) % 360.0 - 180.0


def normalize_heading(angle: float) -> float:
    return angle % 360.0


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def current_real_heading() -> float:
    """시작할 때 저장한 현실 방위를 기준으로 현재 절대방향을 반환한다."""
    if _imu is None or _reference_imu_yaw is None:
        raise RuntimeError("자이로 현실 방향 기준이 설정되지 않았습니다.")
    raw_yaw = float(_imu.angle_z)
    offset = wrapped_delta(raw_yaw, _reference_imu_yaw)
    return normalize_heading(CALIBRATION_HEADING_DEG + offset)


def real_road_heading(nodes: dict, start: str, end: str) -> float:
    dx = nodes[end]["x"] - nodes[start]["x"]
    screen_dy = nodes[end]["y"] - nodes[start]["y"]
    return normalize_heading(math.degrees(math.atan2(-screen_dy, dx)))


def load_turn_calibration() -> None:
    """수동 측정 파일에서 속도 40의 180도 회전 시간을 읽는다."""
    global _turn_seconds_180
    if not TURN_CALIBRATION_PATH.exists():
        raise RuntimeError("회전 보정 파일이 없습니다. turn_180_calibration.py를 먼저 실행하세요.")
    data = json.loads(TURN_CALIBRATION_PATH.read_text(encoding="utf-8"))
    seconds = float(data["seconds_per_180"])
    speed = int(data["turn_speed"])
    if seconds <= 0 or speed != HEADING_FAST_PULSE_SPEED:
        raise RuntimeError(f"회전 보정값이 올바르지 않습니다: 속도={speed}, 시간={seconds}")
    _turn_seconds_180 = seconds
    print(f"회전 보정값 적용: 속도 {speed}, 180° = {seconds:.3f}초")


def rotate_to_real_heading(left_motor, right_motor, target_heading: float) -> None:
    """측정 시간으로 먼저 회전한 뒤 자이로 오차를 15도씩 보정한다."""
    if _turn_seconds_180 is None:
        raise RuntimeError("180도 회전 시간이 로드되지 않았습니다.")
    target_heading = normalize_heading(target_heading)
    started_at = time.monotonic()

    for correction_no in range(1, MAX_HEADING_CORRECTIONS + 1):
        current = current_real_heading()
        error = car_route_v2.normalize_angle(target_heading - current)
        if abs(error) <= ABSOLUTE_HEADING_TOLERANCE_DEG:
            print(f"  절대방향 완료: 목표 {target_heading:.1f}°, 현재 {current:.1f}°, 오차 {error:+.1f}°")
            return
        if time.monotonic() - started_at > MAX_ABSOLUTE_TURN_SECONDS:
            raise RuntimeError(
                f"절대방향 회전 제한시간 초과: 목표 {target_heading:.1f}°, 현재 {current:.1f}°"
            )

        motor_sign = (1 if error > 0 else -1) * MOTOR_SIGN_FOR_POSITIVE_YAW
        if correction_no == 1:
            pulse_speed = HEADING_FAST_PULSE_SPEED
            pulse_target_degrees = abs(error)
        else:
            pulse_speed = HEADING_PULSE_SPEED
            pulse_target_degrees = min(abs(error), HEADING_DEGREES_PER_PULSE)
        pulse_seconds = (
            _turn_seconds_180 * pulse_target_degrees / 180.0 * HEADING_FAST_PULSE_SPEED / pulse_speed
        )
        pulse_seconds = clamp(pulse_seconds, HEADING_PULSE_MIN_SECONDS, HEADING_PULSE_MAX_SECONDS)

        print(
            f"  {'기본 회전' if correction_no == 1 else '오차 보정'} {correction_no}: "
            f"현재 {current:.1f}° → 목표 {target_heading:.1f}° "
            f"(오차 {error:+.1f}°, 이번 목표 {pulse_target_degrees:.1f}°, "
            f"속도 {pulse_speed}, {pulse_seconds:.3f}초)"
        )
        car_route_v2.set_motor_speeds(
            left_motor,
            right_motor,
            pulse_speed * motor_sign,
            pulse_speed * motor_sign,
        )
        try:
            time.sleep(pulse_seconds)
        finally:
            car_route_v2.stop_motors(left_motor, right_motor)
        time.sleep(HEADING_SETTLE_SECONDS)

    current = current_real_heading()
    error = car_route_v2.normalize_angle(target_heading - current)
    raise RuntimeError(
        f"방향 보정 {MAX_HEADING_CORRECTIONS}회 실패: "
        f"목표 {target_heading:.1f}°, 현재 {current:.1f}°, 오차 {error:+.1f}°"
    )


def follow_path_by_real_heading(
    left_motor, right_motor, route_map: dict, path: list[str], current_heading: float
) -> float:
    """각 도로의 절대방위로 회전한 후 기존 직진 제어를 사용한다."""
    del current_heading
    nodes = route_map["nodes"]
    last_heading = current_real_heading()
    for start, end in zip(path, path[1:]):
        target_heading = real_road_heading(nodes, start, end)
        rotate_to_real_heading(left_motor, right_motor, target_heading)
        road_distance = car_route_v2.distance_between(nodes, start, end)
        car_route_v2.drive_distance(left_motor, right_motor, road_distance)
        last_heading = target_heading
        print(f"  도착: {nodes[end]['name']}")
    return last_heading


def gyro_rotate_car(left_motor, right_motor, angle: float) -> None:
    """IMU yaw 변화량을 누적하여 지정 각도만큼 제자리 회전한다."""
    if _imu is None:
        raise RuntimeError("IMU가 초기화되지 않았습니다.")
    angle = car_route_v2.normalize_angle(angle)
    target = abs(angle)
    if target < MIN_TURN_DEG:
        return

    direction = 1 if angle > 0 else -1
    motor_direction = direction * car_route_v2.TURN_DIRECTION_SIGN
    signed_rotation = 0.0
    previous_yaw = float(_imu.angle_z)
    started_at = time.monotonic()
    last_motion_at = started_at
    slowed = False

    car_route_v2.set_motor_speeds(
        left_motor,
        right_motor,
        TURN_SPEED_FAST * motor_direction,
        TURN_SPEED_FAST * motor_direction,
    )
    try:
        while abs(signed_rotation) < max(0.0, target - STOP_BEFORE_TARGET_DEG):
            now = time.monotonic()
            if now - started_at > MAX_TURN_SECONDS:
                raise RuntimeError(
                    f"회전 제한시간 초과: 목표 {target:.1f}°, 순회전 {abs(signed_rotation):.1f}°"
                )
            current_yaw = float(_imu.angle_z)
            if not math.isfinite(current_yaw):
                raise RuntimeError("회전 중 IMU angle_z 값이 올바르지 않습니다.")
            delta = wrapped_delta(current_yaw, previous_yaw)
            previous_yaw = current_yaw
            if abs(delta) >= 0.05:
                signed_rotation += delta
                last_motion_at = now
            remaining = target - abs(signed_rotation)
            if not slowed and remaining <= SLOW_DOWN_REMAINING_DEG:
                car_route_v2.set_motor_speeds(
                    left_motor,
                    right_motor,
                    TURN_SPEED_SLOW * motor_direction,
                    TURN_SPEED_SLOW * motor_direction,
                )
                slowed = True
            if now - last_motion_at > GYRO_STALE_TIMEOUT_SECONDS:
                raise RuntimeError("IMU 회전값이 변하지 않습니다. 센서 장착과 연결을 확인하세요.")
            time.sleep(GYRO_POLL_SECONDS)
    finally:
        car_route_v2.stop_motors(left_motor, right_motor)


def main() -> None:
    load_turn_calibration()
    car_route_v2.connect_modi = connect_ble_with_imu
    car_route_v2.set_motor_speeds = set_four_wheel_speeds
    car_route_v2.stop_motors = stop_four_wheels
    car_route_v2.follow_path = follow_path_by_real_heading
    car_route_v2.main()


if __name__ == "__main__":
    main()
