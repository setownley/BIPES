"""Regression tests for the BIPES robot motion API against fake hardware."""
import importlib
import json
import os
import shutil
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, FW)
import fakehw

fails = []


def check(label, condition, detail=""):
    print(("  PASS  " if condition else "  FAIL  ") + label)
    if not condition:
        if detail:
            print("        " + detail)
        fails.append(label)


fakehw.install()
scratch = tempfile.mkdtemp(prefix="bipes_motion_test_")
os.chdir(scratch)
with open("robot_settings.txt", "w") as output:
    output.write("OS_TIMER=0\n")
with open("mmcal.json", "w") as output:
    json.dump({"Km": 2.0, "Tm": 0.18, "deadband": 20,
               "kP": 2.0, "kD": 0.0}, output)
with open("maze_cal.json", "w") as output:
    json.dump({"breakaway_A": 100, "breakaway_B": 100,
               "trim": {"A": 1.0, "B": 1.0}}, output)

gyro = types.ModuleType("gyro")
gyro._gyro = object()
gyro.bus_lock = types.SimpleNamespace(busy=False)
gyro.angle = 0.0
gyro.callback = None
gyro.gyro_reset = lambda: setattr(gyro, "angle", 0.0)
gyro.gyro_turn = lambda: gyro.angle
gyro.gyro_callback = lambda callback: setattr(gyro, "callback", callback)
gyro.gyro_bus = lambda: gyro.bus_lock
sys.modules["gyro"] = gyro
sys.modules.pop("robot", None)
robot = importlib.import_module("robot")

watchdog_feeds = []
robot.set_watchdog_feed(lambda: watchdog_feeds.append(True))
robot._sleep_ms(1)
check("trusted waits feed the supervisor watchdog before and after sleeping",
      len(watchdog_feeds) == 2, repr(len(watchdog_feeds)))


def duties():
    return {name: channel.duty() for name, channel in robot._pwm.items()}


check("servo PWM is electrically off after runtime import",
      robot._servo.duty_u16() == 0, repr(robot._servo.duty_u16()))

print("Forward gyro hold")
robot.forward_at(300)
gyro.callback(0.0)
first = duties()
check("robot and gyro share one cooperative I2C lock",
      robot._gyro_bus_lock is gyro.bus_lock)
tick_before = robot._tick
gyro.bus_lock.busy = True
robot._tick_cb(None)
gyro.bus_lock.busy = False
check("dashboard timer skips I2C while gyro owns the bus",
      robot._tick == tick_before)
check("forward full-duty launch staggers the second wheel",
      first["A1"] > 0 and first["A2"] == 0
      and first["B2"] == 0 and first["B1"] == 0, repr(first))
check("grout launch stays at the brownout-safe electrical limit",
      0 < max(first.values()) <= robot.POWER_SAFE_MAX,
      repr(first))
# Advance the controller beyond the staggered launch; ordinary driving and
# steering may use the separately bounded one-wheel correction ceiling.
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
gyro.callback(0.0)
cruise = duties()
check("forward cruise uses A1 and B2", cruise["A1"] > 0 and cruise["A2"] == 0
      and cruise["B2"] > 0 and cruise["B1"] == 0, repr(cruise))
gyro.callback(5.0)
corrected = duties()
check("positive yaw produces the verified forward correction",
      corrected["A1"] < corrected["B2"], repr(corrected))
check("heading correction cannot exceed its one-wheel correction cap",
      max(corrected.values()) <= robot.DRIVE_CORRECTION_MAX, repr(corrected))
check("straight integral is disabled to prevent long-run hunting",
      robot._drive_integral == 0, repr(robot._drive_integral))
gyro.callback(30.0)
floor_corrected = duties()
check("large forward drift uses one brownout-safe grout recovery wheel",
      floor_corrected["A1"] == 0
      and floor_corrected["B2"] == robot.DRIVE_RECOVERY_DUTY
      and sum(value > 0 for value in floor_corrected.values()) == 1,
      repr(floor_corrected))
gyro.callback(3.0)
recovered = duties()
check("grout recovery exits through a staggered one-wheel rejoin",
      robot._drive_recovery_sign == 0
      and robot._launch_until is not None
      and sum(value > 0 for value in recovered.values()) == 1,
      repr(recovered))
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
gyro.callback(3.0)
rejoined = duties()
check("grout recovery returns to two-wheel drive after stagger",
      rejoined["A1"] >= robot.get_breakaway()[0]
      and rejoined["B2"] >= robot.get_breakaway()[1], repr(rejoined))
robot.stop()
check("stop releases every motor output", all(value == 0 for value in duties().values()),
      repr(duties()))
check("stop clears the motor safety deadline", robot._motion_deadline is None)
saved_trim = robot.get_trim()
robot.set_trim(1.0, 0.8)
robot.forward_at(220)
check("a new movement resets straight integral state",
      robot._drive_integral == 0, repr(robot._drive_integral))
gyro.callback(0.0)
trimmed_launch = duties()
check("gyro drive launch uses requested duty instead of a fixed 300 kick",
      max(trimmed_launch.values()) <= 220, repr(trimmed_launch))
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
gyro.callback(0.0)
trimmed_cruise = duties()
check("gyro drive applies saved trim as closed-loop feed-forward",
      trimmed_cruise["A1"] == 220 and trimmed_cruise["B2"] == 176,
      repr(trimmed_cruise))
robot.stop()
robot.set_trim(*saved_trim)
fakehw.PWM_WRITES[:] = []
robot.forward_at(300)
gyro.callback(0.0)
robot.stop()
check("stop uses the TB6612 full-high short-brake state then releases it",
      robot.BRAKE_LEVEL in fakehw.PWM_WRITES
      and all(value == 0 for value in duties().values()),
      repr(fakehw.PWM_WRITES))

# room_scan stops and discards Timer 1. The next motion must publish the new
# gyro lock before restarting Timer 0, or both callbacks can enter hardware
# I2C through different locks.
old_timer_start = robot._timer_start
new_lock = types.SimpleNamespace(busy=False)
restart_locks = []
robot._tim = types.SimpleNamespace(deinit=lambda: None)
gyro._gyro = None
def setup_replacement_gyro(i2c=None):
    gyro._gyro = object()
    gyro.bus_lock = new_lock
    return gyro._gyro
gyro.gyro_setup = setup_replacement_gyro
robot._timer_start = lambda: restart_locks.append(robot._gyro_bus_lock)
robot._hold_on(20, 0, spin=True)
check("new gyro I2C lock is published before dashboard timer restarts",
      restart_locks == [new_lock], repr(restart_locks))
robot._hold_off()
robot._timer_start = old_timer_start
robot._tim = None

print("Motor command deadline")
robot.clear_abort()
robot.forward_at(300)
gyro.callback(0.0)
robot._arm_motion_deadline(0)
expired = robot._check_motion_deadline()
check("expired command lease immediately kills every motor", expired and all(
      value == 0 for value in duties().values()), repr(duties()))
robot.forward_at(300)
gyro.callback(0.0)
check("expired lease latches motion off for the rest of the run",
      all(value == 0 for value in duties().values()), repr(duties()))
robot.clear_abort()

print("Uncalibrated electrical ceiling")
check("BIPES named speeds are distinct and power-safe",
      robot.SPEEDS["slow"] < robot.SPEEDS["medium"] < robot.SPEEDS["fast"]
      and robot.SPEEDS["fast"] <= robot.POWER_SAFE_MAX,
      repr(robot.SPEEDS))
check("every fresh-calibration breakaway probe is power-safe",
      robot.CAL_POWER_MAX == robot.POWER_SAFE_MAX
      and max(robot.BREAKAWAY_PROBES) == robot.POWER_SAFE_MAX,
      repr(robot.BREAKAWAY_PROBES))
saved_breakaway = robot.get_breakaway()
check("manual breakaway values are clamped to safe power",
      robot.set_breakaway(999, -1) == (robot.POWER_SAFE_MAX, 0),
      repr(robot.get_breakaway()))
robot.set_breakaway(*saved_breakaway)
robot.raw_forward(999)
check("raw forward is capped and leased",
      max(duties().values()) <= robot.POWER_SAFE_MAX
      and robot._motion_deadline is not None, repr(duties()))
robot.stop()
robot._drive_one("A", 999)
check("single-wheel bench drive is capped and leased",
      max(duties().values()) <= robot.POWER_SAFE_MAX
      and robot._motion_deadline is not None, repr(duties()))
robot.stop()
robot._motors_raw(999, False, 999, False)
check("raw controller writes are capped and leased",
      max(duties().values()) <= robot.POWER_SAFE_MAX
      and robot._motion_deadline is not None, repr(duties()))
robot.stop()
saved_km, saved_kp = robot._km, robot._kp
robot._km = robot._kp = 0
robot.forward("slow")
check("uncalibrated forward is capped at safe duty",
      max(duties().values()) <= robot.POWER_SAFE_MAX, repr(duties()))
robot.stop()
robot.backward("slow")
check("uncalibrated backward is capped at safe duty",
      max(duties().values()) <= robot.POWER_SAFE_MAX, repr(duties()))
robot.stop()
robot.turn("left")
check("continuous turn block is capped at safe duty",
      max(duties().values()) <= robot.POWER_SAFE_MAX, repr(duties()))
robot.stop()
robot._km, robot._kp = saved_km, saved_kp

print("Backward gyro hold")
robot.backward_at(300)
gyro.callback(0.0)
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
gyro.callback(0.0)
first = duties()
check("backward uses A2 and B1", first["A2"] > 0 and first["A1"] == 0
      and first["B1"] > 0 and first["B2"] == 0, repr(first))
gyro.callback(5.0)
corrected = duties()
check("reverse positive yaw inverts the wheel correction",
      corrected["A2"] > corrected["B1"], repr(corrected))
gyro.callback(30.0)
reverse_recovery = duties()
check("large reverse drift flips the one-wheel recovery direction",
      reverse_recovery["A2"] == robot.DRIVE_RECOVERY_DUTY
      and reverse_recovery["B1"] == 0
      and sum(value > 0 for value in reverse_recovery.values()) == 1,
      repr(reverse_recovery))

print("Gyro nudge")
original_sleep_ms = robot._sleep_ms
during_nudge = []
sleep_count = [0]
def nudge_sleep(ms):
    during_nudge.append(duties())
    sleep_count[0] += 1
    if sleep_count[0] > robot.GRIP_LAUNCH_MS // robot.LOOP_MS:
        gyro.angle = -10.0
robot._sleep_ms = nudge_sleep
fakehw.PWM_WRITES[:] = []
error = robot.nudge("left", 10)
robot._sleep_ms = original_sleep_ms
check("nudge keeps the robot moving without braking",
      during_nudge and all(max(sample.values()) > 0 for sample in during_nudge)
      and robot.BRAKE_LEVEL not in fakehw.PWM_WRITES,
      repr((during_nudge, fakehw.PWM_WRITES)))
check("nudge keeps reverse drive and heading hold active",
      robot._hold and robot._reverse_motion and not robot._spin_mode
      and max(duties().values()) > 0)
check("nudge reports its approximate rolling residual", error == 0.0,
      repr(error))
robot.stop()

print("Closed-loop turn stop compensation")
fakehw.PWM_WRITES[:] = []
robot.clear_abort()
robot._hold_on(32.5, 0, spin=True, reverse=False)
robot._steer_heading(0.0)
launch_a = duties()
check("turn launch energises only one wheel at a time",
      sum(value > 0 for value in launch_a.values()) == 1
      and max(launch_a.values()) <= robot.TURN_LAUNCH_DUTY,
      repr(launch_a))
robot._launch_until = robot.time.ticks_add(
    robot.time.ticks_ms(), robot.TURN_LAUNCH_MS // 4)
robot._steer_heading(0.0)
launch_b = duties()
check("second turn launch phase transfers to the other wheel",
      sum(value > 0 for value in launch_b.values()) == 1
      and launch_a != launch_b, repr(launch_b))
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
robot._last_angle = -1.0  # launch made progress; enter ordinary capped control
robot._steer_heading(0.0)
check("closed-loop turns use the measured low-current ceiling",
      max(duties().values()) <= robot.TURN_POWER_MAX, repr(duties()))
robot._steer_heading(20.0)  # high measured rate enters predictive braking
check("predictive turn braking enters the documented short-brake state",
      robot._braking and all(value == robot.BRAKE_LEVEL
                             for value in duties().values()), repr(duties()))
robot._steer_heading(20.3)  # still moving: remain latched, do not reverse-drive
check("turn brake stays latched while the gyro still sees motion",
      robot._braking and all(value == robot.BRAKE_LEVEL
                             for value in duties().values()), repr(duties()))
robot._steer_heading(20.35)  # stopped but well short: resume bounded correction
check("turn brake releases only after stop and resumes bounded drive",
      not robot._braking and max(duties().values()) <= robot.POWER_SAFE_MAX,
      repr(duties()))
robot.stop()
robot._hold_on(7.5, 0, spin=True, reverse=False)
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
robot._braking = True
robot._last_angle = 2.45
robot._steer_heading(2.5)
check("small turn cannot settle more than requested tolerance short",
      not robot._braking and not robot._settled
      and robot._spin_relaunch_remaining == robot.TURN_RELAUNCH_ATTEMPTS - 1
      and sum(value > 0 for value in duties().values()) == 1
      and max(duties().values()) <= robot.TURN_LAUNCH_DUTY,
      repr(duties()))
for _ in range(robot.TURN_RELAUNCH_ATTEMPTS - 1):
    robot._launch_until = None
    robot._braking = True
    robot._last_angle = 2.45
    robot._steer_heading(2.5)
check("turn correction permits a bounded set of grout restarts",
      robot._spin_relaunch_remaining == 0
      and robot._launch_until is not None
      and sum(value > 0 for value in duties().values()) == 1,
      repr(duties()))
robot._launch_until = None
robot._braking = True
robot._last_angle = 2.45
robot._steer_heading(2.5)
check("turn correction cannot relaunch after its retry budget",
      robot._launch_until is None and robot._spin_relaunch_remaining == 0
      and 0 < max(duties().values()) <= robot.TURN_POWER_MAX,
      repr(duties()))
robot.stop()
robot._hold_on(32.5, 0, spin=True, reverse=False)
robot._launch_until = robot.time.ticks_add(robot.time.ticks_ms(), -1)
robot._last_angle = 0.0
robot._steer_heading(0.0)
check("a completely stalled launch spends a bounded grout retry",
      robot._spin_relaunch_remaining == robot.TURN_RELAUNCH_ATTEMPTS - 1
      and robot._launch_until is not None
      and sum(value > 0 for value in duties().values()) == 1
      and max(duties().values()) <= robot.TURN_LAUNCH_DUTY,
      repr(duties()))
robot.stop()
original_hold_on = robot._hold_on
captured_turn_targets = []
def capture_turn_target(target, base, spin, reverse=False):
    captured_turn_targets.append(target)
    robot._set_settled(True)
robot._hold_on = capture_turn_target
gyro.gyro_turn = lambda: -30.0
left_error = robot.turn_degrees("left", 30)
gyro.gyro_turn = lambda: 30.0
right_error = robot.turn_degrees("right", 30)
robot._hold_on = original_hold_on
check("turn controller aims past the measured anti-hunt stopping offset",
      captured_turn_targets == [-32.5, 32.5], repr(captured_turn_targets))
check("turn result is still error from the requested angle",
      left_error == 0.0 and right_error == 0.0,
      repr((left_error, right_error)))

print("Calibration safety")
check("no echo is treated as open space",
      robot._cal_guard_clearance() == robot.NO_ECHO_MM)
check("in-place calibration uses the documented clearance floor",
      robot.CAL_CLEARANCE_MM == 160, robot.CAL_CLEARANCE_MM)
check("pure spins only stop at actual collision clearance",
      robot.CAL_SPIN_CLEARANCE_MM == 30
      and robot.CAL_SPIN_CLEARANCE_MM < robot.CAL_CLEARANCE_MM,
      robot.CAL_SPIN_CLEARANCE_MM)
original_wheel_rate = robot._wheel_rate
health_rates = {("A", False): 380.0, ("A", True): 340.0,
                ("B", False): 310.0, ("B", True): 315.0}
health_probe_modes = []
def fake_health_rate(ch, duty, reverse=False, brake_other=True):
    health_probe_modes.append(brake_other)
    return health_rates[(ch, reverse)]
robot._wheel_rate = fake_health_rate
health = robot._verify_motor_health()
health_trim = robot._trim_from_health(health)
check("calibration health gate verifies both directions of both motors",
      health["A"]["typical"] == 360.0
      and health["B"]["typical"] == 312.5
      and health_probe_modes == [False, False, False, False],
      repr((health, health_probe_modes)))
check("loaded motor rates produce a bounded automatic trim estimate",
      abs(health_trim[0] - (312.5 / 360.0)) < 0.001
      and health_trim[1] == 1.0, repr(health_trim))
trim_before_failed_health = robot.get_trim()
robot._wheel_rate = lambda ch, duty, reverse=False, brake_other=True: (
    0.0 if ch == "A" else 310.0)
check("a disconnected motor fails calibration before saved gains are reused",
      robot._verify_motor_health() is None
      and robot.get_trim() == trim_before_failed_health)
robot._wheel_rate = original_wheel_rate
checkpoint = {"schema": robot.CAL_STATE_VERSION,
              "starts": {"A": 150, "B": 135}, "sweep_index": 2}
robot._save_cal_state(checkpoint)
check("calibration checkpoints survive an interrupted run",
      robot._load_cal_state() == checkpoint, repr(robot._load_cal_state()))
legacy_checkpoint = {"schema": robot.CAL_STATE_VERSION - 1,
                     "sweep": [300, 340, 380, 420, 460]}
robot._save_cal_state(legacy_checkpoint)
check("legacy high-power calibration checkpoints are rejected",
      robot._load_cal_state() == {}, repr(robot._load_cal_state()))
working_kp = robot._kp
robot.reset_characterisation()
check("discarding an unfinished calibration preserves installed gains",
      robot._load_cal_state() == {} and robot._kp == working_kp)
original_turn_degrees = robot.turn_degrees
robot.turn_degrees = lambda direction, degrees: 0.3
validated = robot._validate_characterisation()
robot.turn_degrees = original_turn_degrees
with open(robot.MMCAL_FILE) as validated_file:
    validated_file_data = json.load(validated_file)
check("normal calibration validates existing closed-loop gains",
      validated == (robot._km, robot._tm, robot._dead, robot._kp, robot._kd))
check("validated calibration persists its measured turn bias",
      validated_file_data.get("turn_bias") == robot.TURN_STOP_BIAS_DEG,
      repr(validated_file_data))
original_read = robot._read_ultrasonic_mm
robot._read_ultrasonic_mm = lambda timeout_us=robot.ECHO_TIMEOUT_US: 100
try:
    robot._cal_guard_clearance()
    refused = False
except RuntimeError as exc:
    refused = "clearance 100 mm" in str(exc)
finally:
    robot._read_ultrasonic_mm = original_read
check("calibration refuses a confirmed nearby wall", refused)
check("failed wall guard leaves motors off", all(value == 0 for value in duties().values()),
      repr(duties()))

print("Ultrasonic filtering")
robot._dist_recent[:] = []
filtered = [robot._filter_ultrasonic(value)
            for value in (500, -1, 20, -1, 510)]
check("one short false echo cannot dominate two real echoes",
      filtered[-1] == 500, repr(filtered))
for _ in range(5):
    final = robot._filter_ultrasonic(-1)
check("persistent no-echo becomes unavailable", final == -1, repr(final))

print("Immediate BLE stop latch")
robot.forward_at(300)
gyro.callback(0.0)
robot.emergency_stop()
check("emergency stop immediately zeros PWM",
      all(value == 0 for value in duties().values()), repr(duties()))
robot.forward_at(300)
gyro.callback(0.0)
check("same run cannot restart motors after Stop",
      all(value == 0 for value in duties().values()), repr(duties()))
robot.clear_abort()
robot.forward_at(300)
gyro.callback(0.0)
check("a new run clears the stop latch", any(value > 0 for value in duties().values()),
      repr(duties()))
robot.stop()

print("Calibration log streaming")
streamed = []
robot.set_log_sink(streamed.append)
robot._log("measured line")
robot.set_log_sink(None)
check("calibration line is sent to the active runner", streamed == ["measured line"],
      repr(streamed))
with open(robot.CAL_LOG) as calibration_log:
    check("calibration line remains recoverable from flash",
          "measured line" in calibration_log.read())

os.chdir(HERE)
shutil.rmtree(scratch, ignore_errors=True)
print()
print("ALL PASS" if not fails else "FAILURES: " + repr(fails))
sys.exit(1 if fails else 0)
