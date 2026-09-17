"""Commissioning program behavior with a fake robot and no physical motion."""

import asyncio
import importlib.util
import os
import sys
import types


HERE = os.path.dirname(os.path.abspath(__file__))
PROGRAM = os.environ.get(
    "COMMISSION_PROGRAM",
    os.path.join(os.path.dirname(HERE), "robot_commission.py"),
)
with open(PROGRAM, encoding="utf-8") as source:
    commission_source = source.read()
assert "robot.servo(" not in commission_source
assert "robot.look(" not in commission_source


class PWM:
    def __init__(self):
        self.value = 0

    def duty(self):
        return self.value

    def deinit(self):
        robot.calls.append(("deinit",))


robot = types.ModuleType("robot")
robot.VERSION = "test"
robot.POWER_SAFE_MAX = 550
robot.BRAKE_MS = 300
robot.GRIP_LAUNCH_MS = 60
robot.DRIVE_STEER_GAIN = 2.0
robot.DRIVE_INTEGRAL_GAIN = 0.0
robot.DRIVE_CORRECTION_MAX = 550
robot.MAX_DIFF = 400
robot._kp = 4.0
robot._kd = 0.5
robot.NO_ECHO_MM = 9999
robot._pwm = {name: PWM() for name in ("A1", "A2", "B1", "B2")}
robot._servo = PWM()
robot.calls = []
robot.front = 9999
robot.front_sequence = []
robot.trim = (1.0, 0.92)
robot.distance_mm = lambda: robot.front
robot.side_mm = lambda: 600
robot.calibrated = lambda: True
robot.get_trim = lambda: robot.trim
def set_trim(a=None, b=None):
    current_a, current_b = robot.trim
    robot.trim = (current_a if a is None else float(a),
                  current_b if b is None else float(b))
    return robot.trim
robot.set_trim = set_trim
robot.get_breakaway = lambda: (240, 180)
robot.clear_abort = lambda: robot.calls.append(("clear",))
robot.ping_mm = lambda: robot.front
robot.forward_at = lambda duty: robot.calls.append(("forward", duty))
robot.backward_at = lambda duty: robot.calls.append(("backward", duty))
robot.wait = lambda seconds: robot.calls.append(("wait", seconds))
robot.stop = lambda: robot.calls.append(("stop",))
robot.shutdown = lambda: robot.calls.append(("shutdown",))
robot.set_watchdog_feed = lambda callback: robot.calls.append(("watchdog", callback))
robot.turn_degrees = lambda direction, degrees: 1.25
robot.nudge = lambda direction, degrees: -0.5
robot.characterise = lambda: (1.7, 0.12, 18, 6.2, 0.35)
sys.modules["robot"] = robot

machine = types.ModuleType("machine")
machine.reset_cause = lambda: 1
sys.modules["machine"] = machine

gyro = types.ModuleType("gyro")
gyro._gyro = object()
gyro.gyro_turn = lambda: 2.0
gyro.gyro_stop = lambda: robot.calls.append(("gyro_stop",))
sys.modules["gyro"] = gyro

spec = importlib.util.spec_from_file_location("robot_commission", PROGRAM)
program = importlib.util.module_from_spec(spec)
spec.loader.exec_module(program)


class Context:
    def __init__(self, value):
        self.input = value
        self.events = []
        self._server = types.SimpleNamespace(feed_watchdog=lambda: None)

    async def sleep_ms(self, milliseconds):
        if robot.front_sequence:
            robot.front = robot.front_sequence.pop(0)

    def emit(self, value):
        self.events.append(value)


async def run(value):
    robot.calls[:] = []
    context = Context(value)
    result = await program.main(context)
    return result, context.events, list(robot.calls)


async def main():
    result, events, calls = await run({"action": "status"})
    assert result["front_mm"] == 9999
    assert result["pwm"] == {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
    assert not any(call[0] in ("forward", "backward") for call in calls)
    assert events[-1] == result

    result, _, calls = await run({"action": "straight", "direction": "forward",
                                  "duty": 999, "seconds": 9})
    assert ("forward", 550) in calls
    assert calls[-1] == ("stop",)
    assert result["duty"] == 550 and result["seconds"] == 3.0
    assert len(result["yaw_samples"]) == 60
    assert result["elapsed_seconds"] == 3.0
    assert result["stopped_early"] is False

    result, _, calls = await run({"action": "straight", "direction": "backward",
                                  "seconds": 9})
    assert ("backward", 450) in calls
    assert calls[-1] == ("stop",)
    assert len(result["yaw_samples"]) == 10, repr(result["yaw_samples"])

    robot.front = 200
    try:
        await run({"action": "straight", "direction": "forward"})
        raise AssertionError("near-wall forward test was accepted")
    except RuntimeError as exc:
        assert "clearance 200 mm" in str(exc)
        assert robot.calls[-1] == ("stop",)
    finally:
        robot.front = 9999

    robot.front = 800
    try:
        await run({"action": "straight", "direction": "forward",
                   "seconds": 3})
        raise AssertionError("long forward test without open range was accepted")
    except RuntimeError as exc:
        assert "open-range clearance" in str(exc)
        assert robot.calls[-1] == ("stop",)
    finally:
        robot.front = 9999

    robot.front_sequence[:] = [9999, 500, 240]
    result, _, calls = await run({"action": "straight", "direction": "forward",
                                  "seconds": 3})
    assert result["stopped_early"] is True
    assert result["stop_mm"] == 240
    assert result["elapsed_seconds"] == 0.15
    assert calls.count(("stop",)) >= 2
    robot.front = 9999

    result, _, calls = await run({"action": "turn", "direction": "left",
                                  "degrees": 999})
    assert result["degrees"] == 360
    assert result["residual_deg"] == 1.25
    assert calls[-1] == ("stop",)

    result, _, calls = await run({"action": "nudge", "direction": "right",
                                  "degrees": 99, "drive": "forward"})
    assert ("forward", 450) in calls
    assert result["duty"] == 450
    assert result["degrees"] == 45
    assert result["residual_deg"] == -0.5
    assert calls[-1] == ("stop",)

    result, events, calls = await run({"action": "nudge", "direction": "left",
                                       "degrees": 10, "drive": "backward",
                                       "duty": 999})
    assert ("backward", 550) in calls
    assert result["duty"] == 550
    assert events[0]["phase"] == "drive"
    assert events[1]["phase"] == "nudge"
    assert calls[-1] == ("stop",)

    result, events, calls = await run({"action": "calibrate"})
    assert result["calibration"][0] == 1.7
    assert events[0] == {"action": "calibrate", "phase": "starting"}
    assert calls[-1] == ("stop",)

    print("ALL PASS")


asyncio.run(main())
