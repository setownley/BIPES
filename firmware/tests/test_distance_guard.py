"""Tests the Timer-0 ultrasonic forward guard against stubbed hardware."""

import importlib
import os
import shutil
import sys
import tempfile


HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, FW)
import fakehw


fails = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label +
          (("  <- " + detail) if detail and not condition else ""))
    if not condition:
        fails.append(label)


def duties(robot):
    return {name: pwm.duty() for name, pwm in robot._pwm.items()}


fakehw.install()
scratch = tempfile.mkdtemp(prefix="bipes_guard_test_")
os.chdir(scratch)
with open("robot_settings.txt", "w") as settings:
    settings.write("OS_TIMER=1\n")
sys.modules.pop("robot", None)
robot = importlib.import_module("robot")

check("guard clamps its classroom distance range",
      robot.stop_if_close(9999) is False and
      robot._distance_guard_mm == robot.DISTANCE_GUARD_MAX_MM)
robot.stop_if_close(200)
check("guard enables at the requested distance",
      robot._distance_guard_mm == 200)

check("forward starts while the way is clear", robot.forward("medium") is True)
check("forward state and PWM are active",
      robot._motion_direction == 1 and any(duties(robot).values()),
      repr(duties(robot)))

robot._read_ultrasonic_mm = lambda: 150
robot._tick_cb(None)
check("one close Timer-0 ping stops forward PWM immediately",
      robot.stopped_by_distance() is True and
      robot._motion_direction == 0 and
      not any(duties(robot).values()), repr(duties(robot)))
check("heading control is released by the timer stop", robot._hold is False)

check("forward restart is refused while still close",
      robot.forward("fast") is False and not any(duties(robot).values()))

check("backward remains available while close", robot.backward("medium") is True)
backward_duties = duties(robot)
robot._tick_cb(None)
check("close pings do not stop backward motion",
      robot._motion_direction == -1 and any(duties(robot).values()),
      repr(backward_duties))

robot.turn("left")
turn_duties = duties(robot)
robot._tick_cb(None)
check("close pings do not stop an in-place turn",
      robot._motion_direction == 0 and any(duties(robot).values()),
      repr(turn_duties))
robot.stop()

robot._distance_guard_blocked = True
robot._distance_guard_stopped = True
robot._read_ultrasonic_mm = lambda: 230
robot._tick_cb(None)
check("one clear sample does not chatter the latch open",
      robot.stopped_by_distance() is True)
robot._tick_cb(None)
check("two samples beyond hysteresis clear the stopped status",
      robot.stopped_by_distance() is False and
      robot._distance_guard_blocked is False)

robot._read_ultrasonic_mm = lambda: -2
check("no echo never triggers a stop", robot.forward("medium") is True)
robot._tick_cb(None)
check("9999/open-space semantics leave forward motion running",
      robot._motion_direction == 1 and
      robot.stopped_by_distance() is False and
      any(duties(robot).values()))
robot.stop()

robot._distance_guard_blocked = True
robot._set_drive(400, 400, False)
check("a forward nudge cannot bypass a blocked guard",
      not any(duties(robot).values()))
robot._set_drive(400, 400, True)
check("a reverse nudge remains available",
      any(duties(robot).values()))
robot.stop()

check("guard off clears all guard state",
      robot.distance_guard_off() is False and
      robot._distance_guard_mm == 0 and
      robot._distance_guard_blocked is False and
      robot.stopped_by_distance() is False)

os.chdir(HERE)
shutil.rmtree(scratch, ignore_errors=True)
print()
print("ALL PASS" if not fails else "FAILURES: " + repr(fails))
sys.exit(1 if fails else 0)
