"""Measured ESP32 robot commissioning actions over DevLink.

Input examples:
  {"action": "status"}
  {"action": "straight", "direction": "forward", "duty": 450, "seconds": 0.4}
  {"action": "turn", "direction": "left", "degrees": 30}
  {"action": "nudge", "direction": "right", "degrees": 10, "drive": "forward", "duty": 450}
  {"action": "calibrate"}

This program deliberately contains no servo command.
"""

import machine
import robot


FORWARD_SAFE_STOP_MM = 250


def _pwm_state():
    return {name: channel.duty() for name, channel in robot._pwm.items()}


def _gyro_angle():
    try:
        import gyro
        if gyro._gyro is not None:
            return gyro.gyro_turn()
    except Exception:
        pass
    return None


def _snapshot(extra=None):
    result = {
        "robot_version": robot.VERSION,
        "reset_cause": machine.reset_cause(),
        "front_mm": robot.distance_mm(),
        "side_mm": robot.side_mm(),
        "calibrated": robot.calibrated(),
        "trim": robot.get_trim(),
        "breakaway": robot.get_breakaway(),
        "yaw_deg": _gyro_angle(),
        "pwm": _pwm_state(),
    }
    if extra:
        result.update(extra)
    return result


def _number(request, name, default, low, high):
    try:
        value = float(request.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


async def main(ctx):
    request = ctx.input or {"action": "status"}
    action = str(request.get("action", "status")).lower()
    robot.clear_abort()

    if action == "status":
        # Three background samples are required before one valid ultrasonic
        # history is reported. Yielding keeps BLE responsive while Timer 0
        # updates the dashboard and both distance sensors.
        await ctx.sleep_ms(650)
        result = _snapshot({"action": action})
        ctx.emit(result)
        return result

    result = None
    original_brake_ms = robot.BRAKE_MS
    original_launch_ms = robot.GRIP_LAUNCH_MS
    original_trim = robot.get_trim()
    original_drive_steer_gain = robot.DRIVE_STEER_GAIN
    original_drive_integral_gain = robot.DRIVE_INTEGRAL_GAIN
    original_drive_correction_max = robot.DRIVE_CORRECTION_MAX
    original_max_diff = robot.MAX_DIFF
    original_kp = robot._kp
    original_kd = robot._kd
    try:
        if action == "calibrate":
            ctx.emit({"action": action, "phase": "starting"})
            values = robot.characterise()
            result = {"action": action, "calibration": values}

        elif action == "straight":
            direction = str(request.get("direction", "forward")).lower()
            duty = int(_number(request, "duty", 450, 0, robot.POWER_SAFE_MAX))
            maximum = 3.0 if direction == "forward" else 0.5
            seconds = _number(request, "seconds", 0.4, 0, maximum)
            if "brake_ms" in request:
                robot.BRAKE_MS = int(_number(request, "brake_ms", 80, 0, 300))
            if "launch_ms" in request:
                robot.GRIP_LAUNCH_MS = int(
                    _number(request, "launch_ms", 60, 0, 200))
            if "trim_a" in request or "trim_b" in request:
                robot.set_trim(request.get("trim_a", original_trim[0]),
                               request.get("trim_b", original_trim[1]))
            if request.get("invert_steer"):
                robot.DRIVE_STEER_GAIN = -abs(robot.DRIVE_STEER_GAIN)
            if "integral_gain" in request:
                robot.DRIVE_INTEGRAL_GAIN = _number(
                    request, "integral_gain", original_drive_integral_gain,
                    0, 300)
            if "correction_max" in request:
                robot.DRIVE_CORRECTION_MAX = int(_number(
                    request, "correction_max", original_drive_correction_max,
                    robot.POWER_SAFE_MAX, 700))
            if "max_diff" in request:
                robot.MAX_DIFF = int(_number(
                    request, "max_diff", original_max_diff, 0, 500))
            steer_gain = _number(request, "steer_gain", 1.0, 0.5, 2.0)
            if direction == "backward" and "reverse_gain" in request:
                steer_gain = _number(request, "reverse_gain", steer_gain, 0.5, 2.0)
            robot._kp *= steer_gain
            robot._kd *= steer_gain
            if direction == "forward":
                clearance = robot.ping_mm()
                if clearance != robot.NO_ECHO_MM and clearance < 400:
                    raise RuntimeError("forward test refused: clearance %d mm" % clearance)
                if seconds > 0.8 and clearance != robot.NO_ECHO_MM:
                    raise RuntimeError(
                        "long forward test refused: need open-range clearance")
                robot.forward_at(duty)
            elif direction == "backward":
                # There is no rear sensor, hence the shorter hard limit.
                robot.backward_at(duty)
            else:
                raise ValueError("direction must be forward or backward")
            yaw_samples = []
            elapsed_ms = 0
            stopped_early = False
            stop_mm = None
            total_ms = int(seconds * 1000)
            while elapsed_ms < total_ms:
                step_ms = min(50, total_ms - elapsed_ms)
                await ctx.sleep_ms(step_ms)
                elapsed_ms += step_ms
                yaw_samples.append(_gyro_angle())
                if direction == "forward":
                    current_mm = robot.distance_mm()
                    if (current_mm != robot.NO_ECHO_MM and
                            current_mm < FORWARD_SAFE_STOP_MM):
                        robot.stop()
                        stopped_early = True
                        stop_mm = current_mm
                        break
            result = {"action": action, "direction": direction,
                      "duty": duty, "seconds": seconds,
                      "elapsed_seconds": elapsed_ms / 1000.0,
                      "stopped_early": stopped_early,
                      "stop_mm": stop_mm,
                      "brake_ms": robot.BRAKE_MS,
                      "launch_ms": robot.GRIP_LAUNCH_MS,
                      "steer_gain": steer_gain,
                      "motion_yaw_deg": _gyro_angle(),
                      "yaw_samples": yaw_samples}

        elif action == "turn":
            direction = str(request.get("direction", "left")).lower()
            if direction not in ("left", "right"):
                raise ValueError("direction must be left or right")
            degrees = _number(request, "degrees", 30, 0, 360)
            residual = robot.turn_degrees(direction, degrees)
            result = {"action": action, "direction": direction,
                      "degrees": degrees, "residual_deg": residual}

        elif action == "nudge":
            direction = str(request.get("direction", "left")).lower()
            drive = str(request.get("drive", "forward")).lower()
            duty = int(_number(request, "duty", 450, 0, robot.POWER_SAFE_MAX))
            if direction not in ("left", "right"):
                raise ValueError("direction must be left or right")
            ctx.emit({"action": action, "phase": "drive", "drive": drive,
                      "direction": direction, "duty": duty})
            if drive == "forward":
                clearance = robot.ping_mm()
                if clearance != robot.NO_ECHO_MM and clearance < 400:
                    raise RuntimeError("nudge test refused: clearance %d mm" % clearance)
                robot.forward_at(duty)
            elif drive == "backward":
                robot.backward_at(duty)
            else:
                raise ValueError("drive must be forward or backward")
            robot.wait(0.2)
            degrees = _number(request, "degrees", 10, 0, 45)
            ctx.emit({"action": action, "phase": "nudge", "drive": drive,
                      "direction": direction, "duty": duty,
                      "degrees": degrees})
            residual = robot.nudge(direction, degrees)
            robot.wait(0.2)
            result = {"action": action, "drive": drive, "direction": direction,
                      "duty": duty, "degrees": degrees,
                      "residual_deg": residual}

        else:
            raise ValueError("unknown commissioning action: " + action)
    finally:
        robot.stop()
        robot.BRAKE_MS = original_brake_ms
        robot.GRIP_LAUNCH_MS = original_launch_ms
        robot.set_trim(*original_trim)
        robot.DRIVE_STEER_GAIN = original_drive_steer_gain
        robot.DRIVE_INTEGRAL_GAIN = original_drive_integral_gain
        robot.DRIVE_CORRECTION_MAX = original_drive_correction_max
        robot.MAX_DIFF = original_max_diff
        robot._kp = original_kp
        robot._kd = original_kd

    result = _snapshot(result)
    ctx.emit(result)
    return result
