# robot.py — classroom runtime for ESP32-C3 Super Mini robot (01Space OLED variant)
# Deploy to the board's flash root:  mpremote cp robot.py :
# Every BIPES custom block compiles to a one-line call into this module.
#
# HARD RULE FOR THIS FILE: this module is the ONLY code that ever touches
# Timer 0, the sensors, or the OLED. Student-generated code must only call
# the public functions at the bottom.

VERSION = "1.2.61"  # consistent in-place calibration clearance guard

from machine import Pin, I2C, Timer, PWM, ADC, time_pulse_us
import time
import ssd1306

_watchdog_feed_callback = None
MOTION_DEADLINE_MS = 8000
_motion_deadline = None


def set_watchdog_feed(callback=None):
    """Install the supervisor watchdog feeder without importing it here."""
    global _watchdog_feed_callback
    _watchdog_feed_callback = callback


def _feed_watchdog():
    if _watchdog_feed_callback is not None:
        try:
            _watchdog_feed_callback()
        except Exception:
            pass


def _sleep_ms(milliseconds):
    """Sleep inside a trusted robot operation without tripping the watchdog."""
    _feed_watchdog()
    time.sleep_ms(milliseconds)
    _check_motion_deadline()
    _feed_watchdog()


def _arm_motion_deadline(milliseconds=MOTION_DEADLINE_MS):
    """Bound every uninterrupted motor command, even if user code stalls."""
    global _motion_deadline
    _motion_deadline = time.ticks_add(time.ticks_ms(), int(milliseconds))


def _clear_motion_deadline():
    global _motion_deadline
    _motion_deadline = None


def _check_motion_deadline():
    """Hard-stop PWM when a motor command outlives its safety lease."""
    global _motion_deadline, _abort_requested, _hold
    if (_motion_deadline is None or
            time.ticks_diff(time.ticks_ms(), _motion_deadline) < 0):
        return False
    _motion_deadline = None
    _abort_requested = True
    _hold = False
    # Keep this allocation-free because Timer callbacks call it.
    try:
        for channel in _pwm.values():
            channel.duty(0)
    except NameError:  # module initialization has not created PWM yet
        pass
    return True

# ---------------------------------------------------------------------------
# Pin map — single source of truth. Wire the robots to match THIS file.
#
# !! DECISION ENCODED HERE: TRIG=GPIO1 / ECHO=GPIO0 is the BENCH-TESTED
# !! mapping from the verified firmware (handover V1.3). The handover's
# !! "Final Pin Assignment" table says the opposite (TRIG=0/ECHO=1).
# !! This file resolves the conflict in favour of the tested code.
# !! If you wire per the table instead, swap these two numbers.
# ---------------------------------------------------------------------------
PIN_TRIG = 1
PIN_ECHO = 0
PIN_QRE  = 2          # QRE1113 analog out (ADC). Strapping pin — see handover
PIN_A1, PIN_A2 = 3, 4     # DRV8833 AIN1 / AIN2
PIN_B1, PIN_B2 = 7, 10    # DRV8833 BIN1 / BIN2
PIN_LED  = 8          # onboard blue LED, inverted (0 = on)
PIN_BTN  = 9          # BOOT button — runtime read only, never at power-on
PIN_SERVO = 20        # J4 pin 3 — SG90 signal

# Proven values from the classroom BIPES robot.py. This chassis is mounted so
# increasing pulse width turns the sensor left.
SERVO_MIN_US = 500
SERVO_MAX_US = 2400
SERVO_FREQ = 50
SERVO_SETTLE_MS = 350
SERVO_LEFT = 180
SERVO_AHEAD = 90
SERVO_RIGHT = 0

# Teacher tuning knobs -------------------------------------------------------
ECHO_TIMEOUT_US = 15000     # max range = 2577 mm; covers requested 2400 mm
NO_ECHO_MM      = 9999      # clear/open beyond range, or no usable echo
TOF_MAX_VALID_MM = 2200     # VL53L0X raw reads above this = out-of-range (family ceiling ~2 m)
PWM_FREQ        = 1000      # Hz — matches bench-tested exploratory firmware
SPEEDS = {"slow": 350, "medium": 450, "fast": 500}
POWER_SAFE_MAX = 550       # 600 caused repeatable power-on/brownout resets
DRIVE_CORRECTION_MAX = 550 # feedback ceiling; ordinary cruise remains lower
DRIVE_MIN_DUTY = 300       # over twice measured breakaway; no stall/grout drag
DRIVE_STEER_LIMIT = 75     # bounded correction around cruise; prevents drunken hunting
DRIVE_RECOVERY_ENTER_DEG = 8.0
                            # a larger error means one wheel is probably caught
DRIVE_RECOVERY_EXIT_DEG = 4.0
                            # hysteresis prevents rapid grip-pulse chatter
DRIVE_RECOVERY_DUTY = 450   # proven one-wheel launch; 550 browned out in repeats
CAL_POWER_MAX = POWER_SAFE_MAX  # calibration may probe the full hardware-safe range
CAL_CLEARANCE_MM = 160     # sensor-to-wall room for an in-place pivot plus margin
TURN_POWER_MAX = 300       # faster cruise while retaining useful gyro samples
TURN_LAUNCH_DUTY = 450     # sequential one-wheel kick climbed out of tile grout
TURN_LAUNCH_MS = 120       # 60 ms per wheel before both settle at the 300 cap
TURN_RELAUNCH_ATTEMPTS = 3 # bounded retries when a braked wheel sits in grout
LEFT_MOTOR = "A"            # which DRV8833 channel drives the LEFT wheel
FLIP_A = False              # set True if motor A runs backwards for "forward"
FLIP_B = True   # motor B wiring reversed on this chassis - bench-determined 2026-07-07
# ---- gyro closed-loop steering and turns --------------------------------
# Method from Peter Harrison, micromouseonline.com. Everything below was
# arrived at by measuring a real robot; the comments record what went wrong
# so it is not repeated.
MMCAL_FILE   = "mmcal.json"
ZETA         = 0.7      # slightly underdamped: a few percent overshoot
TDS          = 0.60     # settling time. 0.25 gives wn*dt = 0.46 on a
                        # measured robot, far too fast for a 20ms loop --
                        # above about 0.2 a discrete loop oscillates.
LOOP_MS      = 20       # the gyro sampler period: the steering rate
BOOST_MIN_DEG = 3.0     # below this, do not fire the stiction kick: the
                        # pulse is far bigger than the error needs and the
                        # robot just overshoots the other way
TURN_STOP_BIAS_DEG = 2.5
                        # The anti-hunt latch above stops this chassis a nearly
                        # constant 2-3 degrees short (measured in both directions
                        # at 15/30/45 degrees). Aim beyond the requested heading
                        # by that stopping distance, then report error against the
                        # requested heading. This keeps the no-wobble latch while
                        # removing its systematic under-turn.
TURN_SETTLE_HYST_DEG = 4.5
                        # Target includes the stop bias. Accepting a stopped
                        # turn inside this band keeps requested error within
                        # TURN_TOL_DEG; the old 3*tolerance band could accept
                        # only 2.5 degrees of a requested 5-degree turn.
BRAKE_LEAD   = 0.8      # how far ahead to start braking, in units of the
                        # predicted coast distance. 1.0 means brake exactly
                        # when the robot would just reach the target; higher
                        # stops short, lower overshoots. 0.8 measured best
                        # on a simulated robot: worst error 3.4 deg against
                        # 18 with no braking at all.
TURN_RATE_MAX = 250.0   # deg/s. A sampling limit, not a comfort one: at
                        # 20ms, 250 deg/s is 5 degrees per sample and about
                        # 18 samples in a 90 degree turn. One robot spun at
                        # 580 -- 8 samples for the whole turn, and nothing
                        # is controllable in 8 samples.
GYRO_MAX_DPS = 1000.0   # gyro.py sets +/-1000. At the chip's default +/-250
                        # this robot clips at a quarter throttle.
SAT_LIMIT    = 800.0
KICK_DUTY    = 300      # chassis supply browned out on the previous 450 pulse
MAX_DIFF     = 400      # recomputed from the measured plant

_km = _tm = _dead = _kp = _kd = 0.0
_spin_dead = 0.0        # static-friction floor for spinning from rest
_hold = False
_target = 0.0
_base = 0
_base_target = 0
_reverse_motion = False
_spin_mode = False      # explicit. Inferring "am I spinning?" from base == 0
_braking = False        # turn brake latch: do not alternate brake/drive at 50 Hz
                        # turned a drive-forward into a spin on the spot.
_err_old = 0.0
_last_angle = 0.0
_settled = False
_abort_requested = False
_launch_until = None
_spin_relaunch_remaining = 0
_drive_integral = 0.0
_drive_recovery_sign = 0    # one-wheel high-grip correction for grout lock

TICK_MS = 100               # sensor sampling period
RAMP_MS = 60                # short ramp for uncalibrated fallback; avoid stall dwell
RAMP_STEPS = 10             # ... in this many steps (stop() is always instant)
BRAKE_MS = 20               # physical IMU tests: 80 ms added up to 6 deg stop yaw
BRAKE_LEVEL = 1023          # TB6612 IN1=IN2 logic state, not motor drive duty
LAUNCH_HOLD_MS = 20         # only enough for PWM/gearbox take-up
GRIP_LAUNCH_MS = 60         # full-duty stagger; avoids simultaneous motor inrush
DRIVE_STEER_GAIN = 2.0      # measured: 1x ran away to 39 deg; 2x finished at 3.3
DRIVE_INTEGRAL_GAIN = 0.0   # integral caused long alternating tile corrections
DRIVE_INTEGRAL_MAX = 0.0
CAL_GATE_MS = 3000          # kid self-cal: TAP=CAL window at program start
CAL_CURV_MM = 20            # p99 sensor-noise floor; resolves trim errors >= ~4%
CAL_WALL_MIN = 60           # side reading must be inside this band to start
CAL_WALL_MAX = 300
CAL_FRONT_STOP_MM = 250     # abort a cal pass if something is ahead
CAL_PASSES_MAX = 10
# ---- Maze layer (v0.5.0). Derivations for corridor = 300 mm, robot 160 mm:
MAZE_TARGET_MM = 70         # centered: (300 - 160) / 2
MAZE_OPEN_MM = 200          # in-corridor max reading ~140; gap reads >= 300
MAZE_FRONT_STOP_MM = 130    # leaves >130mm center-to-wall for the 233mm spin diagonal
MAZE_KP = 0.0025            # duty fraction per mm of side error (sim-swept)
MAZE_KD_RATIO = 4           # D/P ratio (sim-swept)
MAZE_MAX_STEER = 0.12
# Cascade control: the wall sensor never writes PWM while gyro hold is active.
# Instead it asks the inner gyro loop for a small heading change. This keeps
# the gyro authoritative while the wall provides a drift-free outer reference.
MAZE_HEADING_KP = 0.08      # requested heading degrees per mm of wall error
MAZE_HEADING_KD = 0.20      # requested heading degrees per mm/tick change
MAZE_MAX_HEADING_DEG = 8.0  # wall sensor has deliberately limited authority
MAZE_ADVANCE_MM = 230       # parks the PIVOT at gap center: 120 (sensor->axle) + 150 (half gap) - ~40 (debounce travel)
MAZE_GAP_MM = 450           # 1.5 cells with no wall = treat as open
MAZE_SPEED = "slow"         # 290 mm/s: 29 mm/tick staleness
NUDGE_SLOW = 0.0            # inside wheel coasts briefly; robot never stops
# Nudge rate: seconds of nudging per degree of heading change, ESTIMATED from
# the track width (160 mm), NUDGE_SLOW and the measured medium speed - NOT
# measured. Expect the real angle to be within roughly a factor of 2. Deliberate
# choice: nudge is a "bend a bit" tool, not a precision instrument. Tune this
# ONE number if the class wants nudges closer to the stated angle.
NUDGE_S_PER_DEG = 0.008     # physical trace: 80 ms produced about a 10 deg bend
OLED_EVERY_N_TICKS = 5      # dashboard repaint cadence = 500 ms
CAL_FILE = "qre_cal.txt"
TRIM_FILE = "trim_cal.txt"      # per-robot straight-drive trim (v0.3.0)
MAZE_CAL_FILE = "maze_cal.json" # written by bench.py (v0.3.0)
# OLED visible window: 72x40 glass at buffer origin (28,24) - MEASURED via
# border probe on board #1, 2026-07-07 (o.rect(28,24,72,40,1) hugs all four
# glass edges). Supersedes V1.3's record that (0,15) rendered.
# 8x8 font grid inside window: 9 chars/row, rows y = 24,32,40,48,56.
OLED_X0 = 28
OLED_Y0 = 24

# ---------------------------------------------------------------------------
# Hardware init (module import runs once; MicroPython caches the module)
# ---------------------------------------------------------------------------
_i2c  = I2C(0, scl=Pin(6), sda=Pin(5), freq=400000)
_oled = ssd1306.SSD1306_I2C(128, 64, _i2c)
_gyro_bus_lock = None       # shared with gyro.py once heading control starts

_trig = Pin(PIN_TRIG, Pin.OUT)
_trig.value(0)
_echo = Pin(PIN_ECHO, Pin.IN)

_servo = PWM(Pin(PIN_SERVO))
_servo.freq(SERVO_FREQ)
_servo.duty_u16(0)          # stay quiet until explicitly commanded
_servo_angle = None
_ping_busy = False

_adc = ADC(Pin(PIN_QRE))
_adc.atten(ADC.ATTN_11DB)   # without this, readings clip near ~1.1 V

_btn = Pin(PIN_BTN, Pin.IN, Pin.PULL_UP)   # 0 = pressed
_led = Pin(PIN_LED, Pin.OUT)
_led.value(1)                              # inverted: 1 = off

# VL53L0X side ToF (left wall, maze following) on the SAME I2C bus as the
# OLED (addr 0x29 vs 0x3C). FAIL-SOFT: boards without the sensor still run
# everything else; side_mm() then returns NO_ECHO_MM.
_tof = None
try:
    import vl53l0x_nb
    _tof = vl53l0x_nb.VL53L0X(_i2c)
except (ImportError, OSError) as _e:
    print("robot: no VL53L0X side sensor:", _e)

# Four PWM channels (ESP32-C3 LEDC has 6 — 4 used here, 2 spare)
_pwm = {
    "A1": PWM(Pin(PIN_A1)), "A2": PWM(Pin(PIN_A2)),
    "B1": PWM(Pin(PIN_B1)), "B2": PWM(Pin(PIN_B2)),
}
for _p in _pwm.values():
    _p.freq(PWM_FREQ)
    _p.duty(0)              # motors coasting/off at import

# ---------------------------------------------------------------------------
# Cached sensor state — written ONLY by the Timer 0 callback, read by blocks.
# All module-level (globals) because a Timer callback cannot see locals.
# ---------------------------------------------------------------------------
_dist_mm = -1
_dist_recent = []
_side_mm = -1
_qre_raw = 0
_tick = 0
_student_text = ""
_cal_line = None
_cal_floor = None

_trim = {"A": 1.0, "B": 1.0}   # duty scale per motor channel, 0.5-1.0

def _load_trim():
    global _trim
    try:
        with open(TRIM_FILE) as f:
            a, b = f.read().split(",")
        _trim = {"A": float(a), "B": float(b)}
    except (OSError, ValueError):
        # bench.py also records the accepted trim in maze_cal.json. Use it
        # as the recovery source when the small dedicated file is missing.
        try:
            import json
            with open(MAZE_CAL_FILE) as f:
                saved = json.load(f).get("trim", {})
            _trim = {"A": float(saved["A"]), "B": float(saved["B"])}
            print("robot: restored trim from maze calibration")
        except (OSError, ValueError, KeyError, ImportError, TypeError):
            pass                  # defaults 1.0/1.0
    _trim["A"] = min(max(_trim["A"], 0.5), 1.0)
    _trim["B"] = min(max(_trim["B"], 0.5), 1.0)

_load_trim()

# Launch floor: both motor channels start the ramp AT this duty together so
# both wheels break static friction simultaneously (fixes the launch yaw).
# Measured per robot by bench.run("launch"); 0 = plain ramp (v0.3.1 behavior).
_breakaway = {"A": 0, "B": 0}   # per-wheel since v0.3.5

def _load_breakaway():
    global _breakaway
    try:
        import json
        with open(MAZE_CAL_FILE) as f:
            cal = json.load(f)
        legacy = int(cal.get("breakaway_duty", 0))
        _breakaway = {"A": int(cal.get("breakaway_A", legacy)),
                      "B": int(cal.get("breakaway_B", legacy))}
    except (OSError, ValueError, ImportError):
        pass
    _breakaway["A"] = min(max(_breakaway["A"], 0), POWER_SAFE_MAX)
    _breakaway["B"] = min(max(_breakaway["B"], 0), POWER_SAFE_MAX)
    if _breakaway["A"] == 0 or _breakaway["B"] == 0:
        print("robot: breakaway not calibrated - run bench launch section")

_load_breakaway()

# Side-sensor linear correction: true = m*raw + c, least-squares over the
# measured curve in maze_cal.json (bench.py "side" section). Falls back to
# raw readings (m=1, c=0) with one console note if no usable curve exists.
_side_m, _side_c = 1.0, 0.0

def _load_side_fit():
    global _side_m, _side_c
    try:
        import json
        with open(MAZE_CAL_FILE) as f:
            curve = json.load(f)["side_curve"]
        pts = [(p[1], p[0]) for p in curve if p[1] is not None]
        n = len(pts)
        if n < 2:
            raise ValueError
        sx = sum(p[0] for p in pts)
        sy = sum(p[1] for p in pts)
        sxy = sum(p[0] * p[1] for p in pts)
        sxx = sum(p[0] * p[0] for p in pts)
        _side_m = (n * sxy - sx * sy) / (n * sxx - sx * sx)
        _side_c = (sy - _side_m * sx) / n
    except (OSError, ValueError, KeyError, ImportError):
        print("robot: no side calibration curve - side_mm() is uncorrected")

_load_side_fit()

def _load_cal():
    global _cal_line, _cal_floor
    try:
        with open(CAL_FILE) as f:
            parts = f.read().split(",")
        _cal_line, _cal_floor = int(parts[0]), int(parts[1])
    except (OSError, ValueError, IndexError):
        _cal_line, _cal_floor = None, None

_load_cal()

def _read_ultrasonic_mm(timeout_us=ECHO_TIMEOUT_US):
    # Per verified handover firmware. time_pulse_us RETURNS -1/-2 on timeout
    # on this MicroPython (>=1.14); it does not raise.
    _trig.value(0)
    time.sleep_us(5)
    _trig.value(1)
    time.sleep_us(10)
    _trig.value(0)
    return time_pulse_us(_echo, 1, timeout_us) * 100 // 582

def _filter_ultrasonic(reading):
    """Require a majority of recent echoes and median-filter tile spikes."""
    _dist_recent.append(reading)
    if len(_dist_recent) > 5:
        del _dist_recent[0]
    valid = sorted(value for value in _dist_recent if value >= 0)
    if len(valid) < 3:
        return -1
    return valid[len(valid) // 2]

def _read_qre_avg(n):
    s = 0
    for _ in range(n):
        s += _adc.read()        # 0-4095 (12-bit)
    return s // n

def _repaint():
    # ONLY the timer callback calls this — single-writer rule for I2C/OLED.
    _oled.fill(0)
    d = _dist_mm if _dist_mm >= 0 else NO_ECHO_MM
    line = "?"
    if _cal_line is not None:
        line = "Y" if _on_line_raw() else "n"
    # Positions use the MEASURED window origin (see OLED_X0/OLED_Y0 above).
    _oled.text("D" + str(d) + " L" + line, OLED_X0, OLED_Y0)          # row 1
    if _tof:
        s = _side_mm if _side_mm >= 0 else NO_ECHO_MM
        _oled.text("S" + str(s), OLED_X0, OLED_Y0 + 8)                # row 2
    if _student_text:
        _oled.text(_student_text, OLED_X0, OLED_Y0 + 24)              # row 4
    _oled.show()

def _tick_cb(t):
    # KEEP SHORT. No sleeps. Worst case per tick (calculated, not measured):
    # 15 ms no-echo timeout + ~25 ms OLED repaint = ~40 ms inside 100 ms.
    global _dist_mm, _side_mm, _qre_raw, _tick, _ping_busy
    if _check_motion_deadline():
        return
    if not _ping_busy:
        _dist_mm = _filter_ultrasonic(_read_ultrasonic_mm())
    _qre_raw = _read_qre_avg(5)
    # The gyro samples the same physical I2C peripheral from Timer 1. Claim
    # its cooperative lock across every ToF/OLED transaction so one timer
    # cannot interrupt the other halfway through a bus transfer.
    lock = _gyro_bus_lock
    if lock is not None:
        if lock.busy:
            return
        lock.busy = True
    try:
        if _tof:
            if _tof.reading_available():
                _v = _tof.get_range_value()
                _side_mm = _v if (_v is not None and _v <= TOF_MAX_VALID_MM) else -1
                _tof.start_range_request()      # immediately begin next measure
            elif not _tof.range_started:
                _tof.start_range_request()      # first tick after import
        _tick += 1
        if _tick % OLED_EVERY_N_TICKS == 0:
            _repaint()
    except OSError:
        _side_mm = -1
    finally:
        if lock is not None:
            lock.busy = False

# Background system on/off ---------------------------------------------------
# BIPES' "Robot OS background timer" block (Machine category) can start a
# program with the background system off, so electronics lessons can drive the
# ultrasonic, QRE and OLED directly without Timer 0 fighting them.
#
# The setting lives in a file on flash, written by BIPES before every Run and
# every Save-to-robot, so the IDE and standalone boot share one mechanism.
# Missing, unreadable or malformed file => True => behaviour is exactly as it
# was before this feature existed.
SETTINGS_FILE = "robot_settings.txt"

_tim = None                 # Timer IDs 0-1 only on the C3; 1 is kept free
OS_TIMER = True             # reflects the setting currently applied

def _read_os_timer_setting():
    """OS_TIMER from SETTINGS_FILE. Only a literal 0 turns the timer off; any
    other value, a missing key, an unreadable file or junk means True."""
    try:
        f = open(SETTINGS_FILE)
    except OSError:
        return True
    try:
        for line in f:
            line = line.strip()
            if line.startswith("OS_TIMER="):
                return line[9:].strip() != "0"
    except OSError:
        return True
    finally:
        f.close()
    return True

def _timer_start():
    global _tim
    if _tim is None:
        _tim = Timer(0)
        _tim.init(period=TICK_MS, mode=Timer.PERIODIC, callback=_tick_cb)

def _timer_stop():
    global _tim
    if _tim is not None:
        _tim.deinit()
        _tim = None

def apply_settings():
    """Read SETTINGS_FILE and make Timer 0 match it. Idempotent: safe to call
    when the timer is already in the wanted state, which is what makes it work
    for IDE runs where this module is already in sys.modules and ticking."""
    global OS_TIMER
    OS_TIMER = _read_os_timer_setting()
    if OS_TIMER:
        _timer_start()
    else:
        _timer_stop()
    return OS_TIMER

apply_settings()            # first import honours the file; none => timer on

# ---------------------------------------------------------------------------
# Motor internals
# ---------------------------------------------------------------------------
def _short_brake():
    """Short both motor windings using the TB6612's documented logic state.

    This is not a 1023 drive command: IN1=IN2=HIGH makes both bridge outputs
    LOW so kinetic current decays locally. Drive commands remain capped by
    POWER_SAFE_MAX.
    """
    for channel in _pwm.values():
        channel.duty(BRAKE_LEVEL)


def _apply(target):
    # Soft start: ramp all four channels together from current to target.
    # Reduces the stiction/torque-mismatch lurch when trims differ (v0.3.1).
    if _abort_requested:
        target = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
    if any(target.values()) and _motion_deadline is None:
        _arm_motion_deadline()
    start = {}
    floored = False
    for k in _pwm:
        cur = _pwm[k].duty()
        bk = _breakaway[k[0]]         # per-wheel floor (v0.3.5)
        if cur == 0 and target[k] > 0 and bk > 0:
            cur = bk                  # each wheel launches at ITS OWN breakaway
            floored = True            # then ramps to target (up OR down)
        start[k] = cur
    if floored:
        for k in _pwm:
            if start[k] > 0 and _pwm[k].duty() == 0:
                _pwm[k].duty(start[k])
        _sleep_ms(LAUNCH_HOLD_MS)
    for i in range(1, RAMP_STEPS + 1):
        for k in _pwm:
            _pwm[k].duty(start[k] + (target[k] - start[k]) * i // RAMP_STEPS)
        _sleep_ms(RAMP_MS // RAMP_STEPS)

def _motors(duty_a, rev_a, duty_b, rev_b):
    target = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
    def _ch(ch, duty, reverse):
        duty = min(max(int(duty), 0), POWER_SAFE_MAX)
        a, b = (ch + "1", ch + "2")
        if reverse:
            a, b = b, a
        target[a] = int(duty * _trim[ch])
        target[b] = 0
    _ch("A", duty_a, rev_a != FLIP_A)
    _ch("B", duty_b, rev_b != FLIP_B)
    _apply(target)

def _speed(name):
    requested = SPEEDS.get(str(name).lower(), SPEEDS["medium"])
    return min(requested, POWER_SAFE_MAX)

def _on_line_raw():
    # Polarity-agnostic: "on line" = current reading is on the line side of
    # the midpoint between the two calibration samples.
    mid = (_cal_line + _cal_floor) // 2
    if _cal_line > _cal_floor:
        return _qre_raw > mid
    return _qre_raw < mid

# ---------------------------------------------------------------------------
# PUBLIC API — the only functions blocks may call
# ---------------------------------------------------------------------------
_cur_speed = "medium"       # last speed requested by forward() - nudge holds it

def _motors_raw(duty_a, rev_a, duty_b, rev_b, kick=False):
    """Set duty immediately: no trim, no ramp.

    Trim corrects the motor mismatch open-loop; applying it under a
    controller already correcting the same mismatch makes the two fight.
    The ramp adds lag the derivative term reads as noise.

    kick=True applies the per-wheel breakaway floor first. Needed when
    starting from rest at a low duty: static friction exceeds running
    friction, and breakaway is per wheel, so without it the stiffer wheel
    sits still while the other turns and the robot pivots instead.
    """
    duty_a = min(max(int(duty_a), 0), POWER_SAFE_MAX)
    duty_b = min(max(int(duty_b), 0), POWER_SAFE_MAX)
    if _abort_requested and (duty_a or duty_b):
        duty_a = duty_b = 0
        kick = False
    if (duty_a or duty_b) and _motion_deadline is None:
        _arm_motion_deadline()

    def _raw(ch, duty, reverse):
        a, b = (ch + "1", ch + "2")
        if reverse:
            a, b = b, a
        _pwm[a].duty(int(duty))
        _pwm[b].duty(0)

    if kick and all(_pwm[k].duty() == 0 for k in _pwm) and (duty_a or duty_b):
        ka = min(max(int(duty_a), _breakaway["A"] or KICK_DUTY), POWER_SAFE_MAX)
        kb = min(max(int(duty_b), _breakaway["B"] or KICK_DUTY), POWER_SAFE_MAX)
        _raw("A", ka, rev_a != FLIP_A)
        _raw("B", kb, rev_b != FLIP_B)
        _sleep_ms(LAUNCH_HOLD_MS)

    _raw("A", duty_a, rev_a != FLIP_A)
    _raw("B", duty_b, rev_b != FLIP_B)


def _set_settled(v):
    global _settled
    _settled = v


def _steer_heading(angle):
    """One PD step, called from the gyro sampler at 50Hz.

    NOT named _steer: robot.py already has a _steer(base, err_mm) for wall
    following further down, and the later definition silently wins.

    Harrison's parallel form:
        error = setPos - currentPos
        PWM   = kP*error + kD*(error - errorOld)
    """
    global _err_old, _last_angle, _base, _launch_until, _braking
    global _spin_relaunch_remaining, _drive_integral, _drive_recovery_sign

    if _check_motion_deadline() or not _hold:
        return

    moved = abs(angle - _last_angle)     # before any early return
    _last_angle = angle
    err = _target - angle

    # Once predictive braking starts, hold the electrical brake until the
    # gyro confirms the chassis has stopped. The previous implementation
    # reconsidered the decision every 20 ms and could chatter between full
    # brake and opposite drive near the target.
    if _spin_mode and _braking:
        _short_brake()
        if moved >= 0.15:
            return
        _braking = False
        if abs(err) < TURN_SETTLE_HYST_DEG:
            _set_settled(True)
            _motors_raw(0, False, 0, False)
            return
        if _spin_relaunch_remaining > 0:
            # Sustained duty 160 may not restart a wheel after the predictive
            # brake on tile/grout. Permit one repeat of the sequential
            # single-wheel launch; never raise both opposed motors together
            # and keep the number of high-torque corrections strictly bounded.
            _spin_relaunch_remaining -= 1
            _launch_until = time.ticks_add(time.ticks_ms(), TURN_LAUNCH_MS)

    # Inside tolerance: command nothing and latch, with hysteresis. Without
    # this the robot hunts at the end of every turn -- stops a degree out,
    # the stiction boost fires at full breakaway duty, overshoots, kicks
    # back. A fast wobble, several times.
    # SPINNING ONLY. Driving forward, the target is the heading we started
    # on, so the error is zero on the very first sample -- the latch fires
    # immediately, commands zero duty, and the robot never moves at all.
    # A turn finishes; driving straight does not.
    if _spin_mode and _settled:
        if abs(err) < TURN_SETTLE_HYST_DEG:
            _motors_raw(0, False, 0, False)
            return
        _set_settled(False)
    elif _spin_mode and abs(err) <= TURN_TOL_DEG:
        _set_settled(True)
        _motors_raw(0, False, 0, False)
        return
    elif _spin_mode and moved < 0.15 and abs(err) < BOOST_MIN_DEG:
        # Stopped, and closer than a breakaway kick could correct without
        # throwing it past the target. This IS the answer at that distance.
        _set_settled(True)
        _motors_raw(0, False, 0, False)
        return

    # Break both wheels out of static friction without applying the battery
    # surge of two opposed motors at the higher launch duty. Each half of
    # this short window pivots on one wheel in the requested direction; the
    # ordinary controller then continues with both motors at TURN_POWER_MAX.
    if _spin_mode and _launch_until is not None:
        remaining = time.ticks_diff(_launch_until, time.ticks_ms())
        if remaining > 0 and abs(err) > TURN_TOL_DEG:
            if remaining > TURN_LAUNCH_MS // 2:
                _motors_raw(TURN_LAUNCH_DUTY, err < 0, 0, False)
            else:
                _motors_raw(0, False, TURN_LAUNCH_DUTY, err > 0)
            return
        _launch_until = None

    # A wheel sitting exactly in a grout hollow may not move at all during a
    # launch, so there is no later predictive-brake event to request another
    # attempt. Detect that complete stall here and spend the same bounded
    # retry budget. Each attempt still energises only one wheel at a time.
    if (_spin_mode and _launch_until is None and moved < 0.15
            and abs(err) > BOOST_MIN_DEG and _spin_relaunch_remaining > 0):
        _spin_relaunch_remaining -= 1
        _launch_until = time.ticks_add(time.ticks_ms(), TURN_LAUNCH_MS)
        _motors_raw(TURN_LAUNCH_DUTY, err < 0, 0, False)
        return

    # --- brake if we would overshoot ------------------------------------
    # Reducing the command does NOT slow this robot down. Below the stall
    # duty the motors switch off and it coasts, and at 250 deg/s with a
    # 0.16s time constant that is about 40 degrees of coast it cannot take
    # back. Every large turn overshot by 10% -- 8.8 degrees on a 90, 18 on
    # a 180 -- because the controller was politely asking for less while the
    # robot carried on at full speed.
    #
    # Shorting the windings (both PWM pins high) stops it far faster than
    # coasting. So: predict where it would come to rest and brake once that
    # passes the target.
    if _spin_mode:
        rate = min(moved * (1000.0 / LOOP_MS), TURN_RATE_MAX)
                                                   # deg/s, sampling-clamped
        coast = rate * (_tm or 0.18) * BRAKE_LEAD
        if coast > abs(err):
            _braking = True
            _short_brake()
            _err_old = err
            return

    launching = (not _spin_mode and _launch_until is not None and
                 time.ticks_diff(_launch_until, time.ticks_ms()) > 0)
    if launching:
        remaining = time.ticks_diff(_launch_until, time.ticks_ms())
        if remaining > (GRIP_LAUNCH_MS * 2) // 3:
            # Start one wheel at the requested cruise power, not at the slow
            # breakaway floor. The second wheel joins on the next gyro tick,
            # so the battery never sees both motor inrush currents together.
            launch_a = int(_base_target * _trim["A"])
            _motors_raw(launch_a, _reverse_motion, 0, _reverse_motion)
            return
    if not _spin_mode and _launch_until is not None and not launching:
        # The launch already used the requested safe drive duty with each
        # wheel's measured breakaway floor. Continue directly rather than
        # ramping down and back up across a grout edge.
        _launch_until = None
        _base = _base_target
    elif not _spin_mode and not launching and _base < _base_target:
        # The gyro path bypasses _apply(), so ramp its forward base here.
        # Jumping directly from 0 to 600 browned out this physical board.
        step = max(1, (_base_target + RAMP_STEPS - 1) // RAMP_STEPS)
        _base = min(_base_target, _base + step)

    diff = _kp * err + _kd * (err - _err_old) * (1000.0 / LOOP_MS)
    if not _spin_mode:
        diff *= DRIVE_STEER_GAIN
        # Tile/grout load changes faster than a useful integral can unwind.
        # Keep correction small and local so the chassis does not alternate
        # between full-left and full-right arcs on a long run.
        if diff > DRIVE_STEER_LIMIT:
            diff = DRIVE_STEER_LIMIT
        elif diff < -DRIVE_STEER_LIMIT:
            diff = -DRIVE_STEER_LIMIT
    _err_old = err

    moving = moved > 0.4 * (LOOP_MS / 1000.0) * 30
    if _spin_mode:
        # Boost only from rest, and only when the error justifies the kick.
        if not moving and abs(err) > BOOST_MIN_DEG:
            if diff > 1:
                diff += _spin_dead
            elif diff < -1:
                diff -= _spin_dead
    # Straight driving deliberately does not add the measured static
    # deadband. Both wheels already cruise far above it; adding another 118
    # duty turned small heading errors into violent alternating corrections.

    if diff > MAX_DIFF:
        diff = MAX_DIFF
    elif diff < -MAX_DIFF:
        diff = -MAX_DIFF

    if _spin_mode:
        # Same magnitude, opposite directions. Deriving each wheel's sign
        # separately does not work: one comes out negative, its reverse flag
        # reads False, and the robot drives away in a straight line.
        mag = int(min(abs(diff), TURN_POWER_MAX))
        _motors_raw(mag, diff < 0, mag, diff > 0)
    else:
        drive_base = _base_target if launching else _base
        # Requested base duty remains safety-clamped. This extra ceiling is
        # available only to feedback on one struggling, same-direction wheel.
        drive_limit = DRIVE_CORRECTION_MAX
        # The complete installed gyro path was verified physically in both
        # signs: forward uses diff and reversing flips the steering response.
        correction = -diff if _reverse_motion else diff
        # A grout edge can hold one wheel even at the ordinary correction
        # ceiling.  Continuing to drive the free wheel then creates the long
        # accelerating curve measured on tile (39 degrees in 0.8 seconds).
        # Beyond a real heading error, release the wheel making the error
        # worse and give only the correcting wheel the proven-safe maximum.
        # One motor at the proven 450 launch duty avoids the opposed-motor
        # brownout seen at 600, and zero is preferable to dwelling in the
        # high-current stall band. Exit with hysteresis once straight.
        leaving_recovery = 0
        if (_drive_recovery_sign and
                (abs(err) <= DRIVE_RECOVERY_EXIT_DEG or
                 _drive_recovery_sign * err <= 0)):
            leaving_recovery = _drive_recovery_sign
            _drive_recovery_sign = 0
            # Rejoin the second wheel through the ordinary staggered launch;
            # jumping from one hard-working wheel to both caused a measured
            # supply reset on the physical robot.
            _launch_until = time.ticks_add(time.ticks_ms(), GRIP_LAUNCH_MS)
        elif not _drive_recovery_sign and abs(err) >= DRIVE_RECOVERY_ENTER_DEG:
            _drive_recovery_sign = 1 if err > 0 else -1
        active_recovery = _drive_recovery_sign or leaving_recovery
        if active_recovery:
            recovery = (-active_recovery if _reverse_motion
                        else active_recovery)
            if recovery > 0:
                _motors_raw(DRIVE_RECOVERY_DUTY, _reverse_motion,
                            0, _reverse_motion)
            else:
                _motors_raw(0, _reverse_motion,
                            DRIVE_RECOVERY_DUTY, _reverse_motion)
            return
        base_a = drive_base * _trim["A"]
        base_b = drive_base * _trim["B"]
        duty_a = int(min(max(base_a + correction, 0), drive_limit))
        duty_b = int(min(max(base_b - correction, 0), drive_limit))
        # A correction may reduce the dominant wheel, but never back into the
        # slow high-current/stall region that caused BLE loss on grout.
        floor_a = min(base_a, DRIVE_MIN_DUTY)
        floor_b = min(base_b, DRIVE_MIN_DUTY)
        if duty_a:
            duty_a = min(drive_limit, max(duty_a, floor_a))
        if duty_b:
            duty_b = min(drive_limit, max(duty_b, floor_b))
        _motors_raw(duty_a, _reverse_motion,
                    duty_b, _reverse_motion)


def _hold_on(target, base, spin, reverse=False):
    """Start the heading loop. Does NOT recalibrate the gyro.

    gyro_setup() measures the zero-rate bias, valid only when the robot is
    still. Calling it here meant a program like
        turn('left')      # continuous spin, returns at once
        forward('slow')   # recalibrates... while spinning
    recorded several hundred deg/s as "stationary", after which the
    controller spun a motionless robot to correct an imaginary drift. It
    also cost 700ms before every move.
    """
    global _hold, _target, _base, _base_target, _reverse_motion
    global _err_old, _spin_mode, _last_angle, _braking
    global _gyro_bus_lock, _launch_until, _spin_relaunch_remaining
    global _drive_integral, _drive_recovery_sign
    import gyro
    if gyro._gyro is None:
        # Bias calibration assumes zero angular velocity. A preceding
        # continuous turn() may still be moving, so force a stop before the
        # first setup rather than recording motion as the zero-rate bias.
        stop()
        timer_was_running = _tim is not None
        if timer_was_running:
            _timer_stop()
        try:
            gyro.gyro_setup(i2c=_i2c)
            # Publish the new sampler's lock before Timer 0 is allowed to
            # touch OLED/ToF again. After room_scan calls gyro_stop(), the
            # previous lock remains in this module; restarting Timer 0 first
            # briefly lets Timer 0 and the new Timer 1 use different locks
            # around the same hardware I2C peripheral.
            _gyro_bus_lock = gyro.gyro_bus()
        finally:
            if timer_was_running:
                _timer_start()
    else:
        _gyro_bus_lock = gyro.gyro_bus()
    gyro.gyro_reset()
    _target = target
    _base = 0 if not spin else base
    _base_target = base
    _reverse_motion = bool(reverse)
    _spin_mode = bool(spin)
    _braking = False
    _err_old = target
    _last_angle = 0.0
    _set_settled(False)
    _launch_until = time.ticks_add(
        time.ticks_ms(), TURN_LAUNCH_MS if spin else GRIP_LAUNCH_MS)
    _spin_relaunch_remaining = TURN_RELAUNCH_ATTEMPTS if spin else 0
    _drive_integral = 0.0
    _drive_recovery_sign = 0
    _hold = True
    gyro.gyro_callback(_steer_heading)


def _hold_off():
    global _hold, _launch_until, _braking, _spin_relaunch_remaining
    global _drive_recovery_sign
    _hold = False
    _braking = False
    _launch_until = None
    _spin_relaunch_remaining = 0
    _drive_recovery_sign = 0
    try:
        import gyro
        # Stopping must never initialise/calibrate a gyro or construct a
        # second I2C object merely to clear a callback that cannot exist.
        if gyro._gyro is not None:
            gyro.gyro_callback(None)
    except Exception:
        pass


def calibrated():
    return _km > 0 and _kp > 0


def _load_mmcal():
    global _km, _tm, _dead, _kp, _kd, _spin_dead, MAX_DIFF
    global TURN_STOP_BIAS_DEG
    try:
        import json
        with open(MMCAL_FILE) as f:
            c = json.load(f)
        _km = float(c.get("Km", 0)); _tm = float(c.get("Tm", 0))
        _dead = float(c.get("deadband", 0))
        _kp = float(c.get("kP", 0)); _kd = float(c.get("kD", 0))
        TURN_STOP_BIAS_DEG = float(c.get("turn_bias", TURN_STOP_BIAS_DEG))
        _spin_dead = float(max(_breakaway["A"], _breakaway["B"]))
        if _km > 0:
            MAX_DIFF = int(min(max(_dead, _spin_dead * 0.7)
                               + TURN_RATE_MAX / _km, 1023))
        return True
    except (OSError, ValueError, ImportError, TypeError):
        return False


TURN_TOL_DEG    = 2.0
TURN_HOLD_MS    = 100
TURN_TIMEOUT_MS = 5000


def forward(speed="medium"):
    """Drive forward, holding the heading it started on.

    Same signature and same immediate return as before, so every existing
    block still works. Uncalibrated it falls back to the old open-loop
    behaviour rather than driving on meaningless gains.
    """
    global _cur_speed
    _cur_speed = speed
    d = _speed(speed)
    if not calibrated():
        d = min(d, POWER_SAFE_MAX)
        _motors(d, False, d, False)
        return
    _hold_on(0.0, d, spin=False, reverse=False)

def forward_at(duty):
    """Drive forward at a clamped duty using the same gyro hold as forward."""
    try:
        d = int(duty)
    except (TypeError, ValueError):
        return
    d = min(max(d, 0), POWER_SAFE_MAX)
    if not calibrated():
        _motors(d, False, d, False)
        return
    _hold_on(0.0, d, spin=False, reverse=False)

def backward(speed="medium"):
    """Drive backward while holding the heading it started on."""
    global _cur_speed
    _cur_speed = speed
    d = _speed(speed)
    if not calibrated():
        d = min(d, POWER_SAFE_MAX)
        _motors(d, True, d, True)
        return
    _hold_on(0.0, d, spin=False, reverse=True)

def backward_at(duty):
    """Drive backward at a clamped duty with gyro heading hold."""
    try:
        d = int(duty)
    except (TypeError, ValueError):
        return
    d = min(max(d, 0), POWER_SAFE_MAX)
    if not calibrated():
        _motors(d, True, d, True)
        return
    _hold_on(0.0, d, spin=False, reverse=True)

def turn(direction="left"):
    # spin turn in place at medium speed.
    # Releases the heading loop first: without it a forward() earlier in the
    # program leaves the gyro steering in the background and fights this,
    # and the robot spins away instead of stopping.
    _hold_off()
    d = min(_speed("medium"), POWER_SAFE_MAX)
    if str(direction).lower() == "left":
        left_rev, right_rev = True, False
    else:
        left_rev, right_rev = False, True
    if LEFT_MOTOR == "A":
        _motors(d, left_rev, d, right_rev)
    else:
        _motors(d, right_rev, d, left_rev)

def stop():
    was_active = _hold or any(p.duty() for p in _pwm.values())
    _clear_motion_deadline()
    # Release the heading loop BEFORE braking, or it sees the robot stop,
    # reads a growing error and fights the brake.
    _hold_off()
    if not was_active:
        for p in _pwm.values():
            p.duty(0)
        return
    # Brake first (TB6612 IN1=IN2=HIGH is its short-brake logic state), then
    # release to coast. This 1023 is a digital bridge state, not drive power.
    # Applied INSTANTLY - no ramp on the safety path.
    _short_brake()
    _sleep_ms(BRAKE_MS)
    for p in _pwm.values():
        p.duty(0)           # coast (TB6612 IN1=IN2=LOW), safe state
    # Let the 1 kHz PWM latch the zero before callers inspect the channels or
    # the DevLink supervisor decides whether another safety stop is needed.
    _sleep_ms(2)

def emergency_stop():
    """Fast non-blocking motor kill used directly by the BLE receive path.

    The latch prevents later statements in the same synchronous block program
    from restarting PWM. It is cleared only when DevLink starts a new run.
    """
    global _abort_requested, _hold
    _abort_requested = True
    _hold = False
    _clear_motion_deadline()
    for p in _pwm.values():
        p.duty(0)

def clear_abort():
    """Allow motion for a newly accepted DevLink run."""
    global _abort_requested
    _abort_requested = False
    _clear_motion_deadline()

def wait(seconds):
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        s = 0
    remaining_ms = int(min(max(s, 0), 60) * 1000)
    while remaining_ms > 0 and not _abort_requested:
        part = min(remaining_ms, 20)
        _sleep_ms(part)
        remaining_ms -= part

def distance_mm():
    return _dist_mm if _dist_mm >= 0 else NO_ECHO_MM

def servo(angle):
    """Point the ultrasonic sensor from 0 (right) to 180 (left)."""
    global _servo_angle
    try:
        a = float(angle)
    except (TypeError, ValueError):
        return
    a = min(max(a, 0), 180)
    us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * a / 180.0
    period_us = 1000000.0 / SERVO_FREQ
    _servo.duty_u16(int(65535 * us / period_us))
    _servo_angle = a

def look(where):
    """Point left, ahead/centre, right, or to an angle and wait to settle."""
    global _servo_angle
    if where == "left":
        a = SERVO_LEFT
    elif where == "right":
        a = SERVO_RIGHT
    elif where == "ahead" or where == "centre" or where == "center":
        a = SERVO_AHEAD
    else:
        try:
            a = min(max(float(where), 0), 180)
        except (TypeError, ValueError):
            return

    previous = _servo_angle
    servo(a)
    if previous is None:
        _sleep_ms(SERVO_SETTLE_MS)
    else:
        fraction = abs(a - previous) / 180.0
        _sleep_ms(int(60 + (SERVO_SETTLE_MS - 60) * fraction))

def servo_off():
    """Release the servo so it is quiet and does not draw holding current."""
    _servo.duty_u16(0)

def ping_mm(timeout_ms=None):
    """Take three fresh pings; require two echoes and return their median."""
    global _ping_busy
    if timeout_ms is None:
        timeout_us = ECHO_TIMEOUT_US
    else:
        try:
            timeout_us = int(float(timeout_ms) * 1000)
        except (TypeError, ValueError):
            timeout_us = ECHO_TIMEOUT_US
        timeout_us = min(max(timeout_us, 1000), 30000)

    if _ping_busy:
        return distance_mm()
    _ping_busy = True
    try:
        readings = []
        for _ in range(3):
            value = _read_ultrasonic_mm(timeout_us)
            if value >= 0:
                readings.append(value)
            _sleep_ms(8)
    finally:
        _ping_busy = False
    if len(readings) < 2:
        return NO_ECHO_MM
    readings.sort()
    return readings[len(readings) // 2]

def look_and_measure(where, timeout_ms=None):
    """Point the sensor, wait for it to settle, then take a fresh reading."""
    look(where)
    return ping_mm(timeout_ms)

def side_mm():
    if _side_mm < 0:
        return NO_ECHO_MM
    v = int(_side_m * _side_mm + _side_c)
    return v if v >= 0 else 0

def on_line():
    if _cal_line is None or _cal_floor is None:
        print("robot: line sensor not calibrated - run robot.calibrate()")
        return False
    return _on_line_raw()

def button():
    return _btn.value() == 0

def led(on=True):
    _led.value(0 if on else 1)      # inverted logic

def show(text):
    global _student_text
    _student_text = str(text)[:9]   # exactly 9 chars fit: 72 px / 8 px font
    # painted by the next dashboard tick (<= 500 ms latency by design)

# ---------------------------------------------------------------------------
# Teacher utilities (not exposed as student blocks)
# ---------------------------------------------------------------------------
def _tap(timeout_ms):
    """Wait for the BOOT button. Returns 'tap', 'hold' (>=0.6s) or None."""
    t0 = time.ticks_ms()
    while _btn.value() == 1:
        if time.ticks_diff(time.ticks_ms(), t0) >= timeout_ms:
            return None
        _sleep_ms(20)
    p0 = time.ticks_ms()
    while _btn.value() == 0:
        _sleep_ms(20)
        if time.ticks_diff(time.ticks_ms(), p0) >= 2000:
            break
    return 'hold' if time.ticks_diff(time.ticks_ms(), p0) >= 600 else 'tap'

def _cal_pass():
    """One forward wall run. Returns list of (i, side_mm) samples or None."""
    raw = []
    forward('medium')
    try:
        for i in range(20):
            _sleep_ms(100)
            if distance_mm() < CAL_FRONT_STOP_MM:
                return None
            raw.append(side_mm())
    finally:
        stop()
    # v0.4.3: drop the launch window (first 5) - launch yaw and handling-stale
    # readings live there - then median-of-3 the cruise to kill spikes.
    cruise = raw[5:]
    pts = []
    for i in range(1, len(cruise) - 1):
        w = sorted((cruise[i - 1], cruise[i], cruise[i + 1]))
        if w[1] < NO_ECHO_MM:
            pts.append((i, w[1]))
    return pts if len(pts) >= 10 else None

def _fit_curvature(pts):
    """Quadratic least squares y = a + b*x + c*x**2 over (x, y) points.
    Returns c. The linear term b absorbs the kid's placement angle; only
    c reflects trim-caused curvature (v0.4.2)."""
    S0 = len(pts)
    S1 = S2 = S3 = S4 = 0.0
    Sy = Sxy = Sx2y = 0.0
    for x, y in pts:
        x2 = x * x
        S1 += x; S2 += x2; S3 += x2 * x; S4 += x2 * x2
        Sy += y; Sxy += x * y; Sx2y += x2 * y
    D = S0 * (S2 * S4 - S3 * S3) - S1 * (S1 * S4 - S3 * S2) + S2 * (S1 * S3 - S2 * S2)
    if D == 0:
        return 0.0
    Dc = S0 * (S2 * Sx2y - S3 * Sxy) - S1 * (S1 * Sx2y - S3 * Sy) + S2 * (S1 * Sxy - S2 * Sy)
    return Dc / D

def _selfcal_trim():
    """Kid self-cal v0.4.2: placement-invariant (quadratic fit) with an
    adaptive step. Kid places the robot along a LEFT wall and taps."""
    show("WALL LEFT")
    if _tap(30000) is None:
        return False
    step = 0.02
    last_sign = 0
    for p in range(1, CAL_PASSES_MAX + 1):
        s = side_mm()
        if not (CAL_WALL_MIN < s < CAL_WALL_MAX):
            show("NO WALL")
            if _tap(30000) is None:
                return False
            continue
        show("PASS " + str(p))
        pts = _cal_pass()
        if pts is None:
            show("BLOCKED")
            if _tap(30000) is None:
                return False
            continue
        c = _fit_curvature(pts)
        xr = pts[-1][0] - pts[0][0]
        curv_mm = c * xr * xr          # curvature-attributed offset over the pass
        if abs(curv_mm) <= CAL_CURV_MM:
            save_trim()
            show("DONE")
            return True
        sign = 1 if curv_mm > 0 else -1
        if last_sign and sign != last_sign:
            step = max(step / 2, 0.005)   # crossed the target: finer steps
        last_sign = sign
        a, b = get_trim()
        if sign > 0:
            set_trim(a=a * (1 - step))    # curving away from left wall = right
        else:
            set_trim(b=b * (1 - step))    # curving toward wall = left
        show("PUT BACK")
        if _tap(60000) is None:
            return False
    show("MAX PASS")
    return False

def cal_gate():
    """Prepended to every student program by BIPES Save-to-robot.
    3s window: tap = kid self-cal (then halt); no tap = run the program."""
    show("TAP=CAL")
    if _tap(CAL_GATE_MS) is None:
        show("")
        return
    _selfcal_trim()
    while True:
        time.sleep(1)              # halt; power-cycle to run programs

def calibrate(target):
    """Run from the REPL: hold sensor over the line, call robot.calibrate('line');
    hold over the floor, call robot.calibrate('floor'). Saves to flash."""
    global _cal_line, _cal_floor
    v = _read_qre_avg(20)
    if target == "line":
        _cal_line = v
    elif target == "floor":
        _cal_floor = v
    else:
        print("use 'line' or 'floor'")
        return
    print(target, "=", v)
    if _cal_line is not None and _cal_floor is not None:
        with open(CAL_FILE, "w") as f:
            f.write(str(_cal_line) + "," + str(_cal_floor))
        print("saved:", _cal_line, _cal_floor)

def _drive_one(ch, duty):
    """Bench only: spin ONE channel forward at raw duty (trim NOT applied)."""
    duty = min(max(int(duty), 0), POWER_SAFE_MAX)
    if duty and _motion_deadline is None:
        _arm_motion_deadline()
    flip = FLIP_A if ch == "A" else FLIP_B
    a, b = ((ch + "2", ch + "1") if flip else (ch + "1", ch + "2"))
    _pwm[a].duty(int(duty))
    _pwm[b].duty(0)

def get_breakaway():
    return _breakaway["A"], _breakaway["B"]

def set_breakaway(a, b):
    """Set safe launch floors in RAM (bench launchtune)."""
    _breakaway["A"] = min(max(int(a), 0), POWER_SAFE_MAX)
    _breakaway["B"] = min(max(int(b), 0), POWER_SAFE_MAX)
    return _breakaway["A"], _breakaway["B"]

def raw_forward(duty):
    """Teacher/bench only: forward at a fixed raw duty (trimmed, NO ramp)."""
    d = min(max(int(duty), 0), POWER_SAFE_MAX)
    if d and _motion_deadline is None:
        _arm_motion_deadline()
    target = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
    a = ("A2", "A1") if FLIP_A else ("A1", "A2")
    b = ("B2", "B1") if FLIP_B else ("B1", "B2")
    _pwm[a[0]].duty(int(d * _trim["A"])); _pwm[a[1]].duty(0)
    _pwm[b[0]].duty(int(d * _trim["B"])); _pwm[b[1]].duty(0)

# ---------------------------------------------------------------------------
# Maze layer (v0.5.0) - wall following with continuous steering. This is the
# feedback loop that absorbs launch yaw and residual trim error.
# ---------------------------------------------------------------------------
_last_event = ""

def _steer(base_duty, err_mm):
    """Drive forward with a duty differential proportional to side error.
    err > 0 = too far from left wall = steer left (slow the left wheel)."""
    k = err_mm * MAZE_KP
    if k > MAZE_MAX_STEER: k = MAZE_MAX_STEER
    if k < -MAZE_MAX_STEER: k = -MAZE_MAX_STEER
    left = int(base_duty * (1 - k))
    right = int(base_duty * (1 + k))
    if LEFT_MOTOR == "A":
        da, db = left, right
    else:
        da, db = right, left
    a = ("A2", "A1") if FLIP_A else ("A1", "A2")
    b = ("B2", "B1") if FLIP_B else ("B1", "B2")
    _pwm[a[0]].duty(int(da * _trim["A"])); _pwm[a[1]].duty(0)
    _pwm[b[0]].duty(int(db * _trim["B"])); _pwm[b[1]].duty(0)

def follow_wall():
    """Follow the LEFT wall until something changes. Sets the event readable
    by left_open() / front_blocked(). Kid block: 'follow wall until change'."""
    global _last_event, _cur_speed, _target
    base = _speed(MAZE_SPEED)
    mm_per_tick = 29                      # slow, measured 290 mm/s
    if distance_mm() < MAZE_FRONT_STOP_MM:
        _last_event = "front"             # v0.5.1: pre-check BEFORE moving -
        return                            # dead-end second turn fires with zero motion
    _cur_speed = MAZE_SPEED
    forward(MAZE_SPEED)                    # gyro is the sole inner controller
    open_ticks = 0
    gap_mm = 0
    prev_s = None
    try:
        while True:
            _sleep_ms(TICK_MS)
            if _abort_requested:
                return
            if distance_mm() < MAZE_FRONT_STOP_MM:
                _last_event = "front"
                return
            s = side_mm()
            if s >= MAZE_OPEN_MM:
                open_ticks += 1
                gap_mm += mm_per_tick
                if open_ticks >= 2:
                    # wall gone (debounced): clear the gap edge, then report
                    adv = MAZE_ADVANCE_MM
                    while adv > 0:
                        _sleep_ms(TICK_MS)
                        if _abort_requested:
                            return
                        if distance_mm() < MAZE_FRONT_STOP_MM:
                            _last_event = "front"
                            return
                        adv -= mm_per_tick
                    _last_event = "left"
                    return
                if gap_mm >= MAZE_GAP_MM:
                    _last_event = "left"
                    return
                # No trustworthy wall reference across a gap: freeze the
                # present heading instead of continuing the last wall bend.
                import gyro
                _target = gyro.gyro_turn()
            else:
                open_ticks = 0
                gap_mm = 0
                ds = 0 if prev_s is None else (s - prev_s)
                prev_s = s
                # Outer wall loop requests a small heading offset; only the
                # 50Hz gyro loop writes PWM. Positive gyro angle is right, so
                # being too far from the left wall requests a negative/left
                # heading change.
                heading = -(MAZE_HEADING_KP * (s - MAZE_TARGET_MM)
                            + MAZE_HEADING_KD * ds)
                if heading > MAZE_MAX_HEADING_DEG:
                    heading = MAZE_MAX_HEADING_DEG
                elif heading < -MAZE_MAX_HEADING_DEG:
                    heading = -MAZE_MAX_HEADING_DEG
                import gyro
                _target = gyro.gyro_turn() + heading
    finally:
        stop()

def left_open():
    return _last_event == "left"

def front_blocked():
    return _last_event == "front"

def nudge(direction="left", degrees=10):
    """Change the held heading while driving, then carry straight on.

    With gyro heading hold active, this waits for the measured angle and
    leaves the controller holding the new heading. The uncalibrated fallback
    uses a timed estimate. Motors do not stop between the bend and straight.
    """
    global _target
    try:
        d = float(degrees)
    except (TypeError, ValueError):
        d = 0
    d = min(max(d, 0), 180)
    if d == 0:
        return
    direction = str(direction).lower()

    # Nudge is deliberately an in-flight direction change, not a precise turn.
    # Temporarily suspend heading hold (without touching PWM), apply a direct
    # wheel-speed difference, then lock the gyro to the heading actually
    # reached. Both wheels remain powered throughout.
    if _hold and not _spin_mode:
        base = _base_target
        reverse = _reverse_motion
        import gyro
        outer = POWER_SAFE_MAX
        slow = int(outer * NUDGE_SLOW)
        # Reversing swaps which physical wheel is the inside of the arc.
        left_is_slow = ((direction == "left") != reverse)
        left, right = (slow, outer) if left_is_slow else (outer, slow)
        if LEFT_MOTOR == "A":
            da, db = left, right
        else:
            da, db = right, left
        _hold_off()                         # leaves current PWM untouched
        # The normal 220-duty classroom drive can sit on a grout edge. Give
        # both wheels one short, same-direction safe-power grip pulse before
        # creating the arc. This accelerates straight; it never stops/brakes.
        _set_drive(outer, outer, reverse)
        launch_remaining = GRIP_LAUNCH_MS
        while launch_remaining > 0 and not _abort_requested:
            part = min(LOOP_MS, launch_remaining)
            _sleep_ms(part)
            launch_remaining -= part
        start = gyro.gyro_turn()
        _set_drive(da, db, reverse)
        # Keep the direct moving arc until the approximate requested heading
        # is reached. Fixed timing varied wildly between clean tile and grout.
        # This remains an in-flight bend: no stop, brake, or opposed motors.
        requested = -d if direction == "left" else d
        deadline = time.ticks_add(
            time.ticks_ms(), int(min(max(d * 120, 400), 4000)))
        while (time.ticks_diff(deadline, time.ticks_ms()) > 0
               and not _abort_requested):
            _sleep_ms(LOOP_MS)
            actual = gyro.gyro_turn() - start
            if ((requested < 0 and actual <= requested)
                    or (requested > 0 and actual >= requested)):
                break
        actual = gyro.gyro_turn() - start
        if not _abort_requested:
            _hold_on(0.0, base, spin=False, reverse=reverse)
        return requested - actual

    base = _speed(_cur_speed)               # hold whatever speed we are doing
    slow = int(base * NUDGE_SLOW)
    if direction == "left":
        left, right = slow, base
    else:
        left, right = base, slow
    if LEFT_MOTOR == "A":
        da, db = left, right
    else:
        da, db = right, left
    _set_forward(da, db)                    # asymmetric: bend
    _sleep_ms(int(d * NUDGE_S_PER_DEG * 1000))
    _set_forward(base, base)                # straight again - STILL DRIVING

def _set_forward(duty_a, duty_b):
    """Write forward duties directly - no ramp, no stop. Used by nudge so the
    robot keeps rolling through the correction."""
    _set_drive(duty_a, duty_b, False)

def _set_drive(duty_a, duty_b, reverse=False):
    """Direct two-wheel drive used for a continuous approximate nudge."""
    duty_a = min(max(int(duty_a), 0), POWER_SAFE_MAX)
    duty_b = min(max(int(duty_b), 0), POWER_SAFE_MAX)
    if _abort_requested:
        duty_a = duty_b = 0
    if (duty_a or duty_b) and _motion_deadline is None:
        _arm_motion_deadline()
    raw_a = int(duty_a * _trim["A"])
    raw_b = int(duty_b * _trim["B"])
    if raw_a:
        raw_a = max(raw_a, _breakaway["A"] or raw_a)
    if raw_b:
        raw_b = max(raw_b, _breakaway["B"] or raw_b)
    _motors_raw(raw_a, reverse, raw_b, reverse)

def turn_degrees(direction="left", degrees=90):
    """Spin a chosen angle, measured by the gyro.

    Signature unchanged, so every existing block still works.

    Replaces a scheme that scaled one timed measurement, whose own docstring
    listed the damage: under about 15 degrees the launch ramp dominated and
    it under-rotated, large angles accumulated error, and battery level and
    floor surface both shifted the result. A closed loop on measured angle
    stops when the gyro says it has turned far enough, whatever the battery
    is doing.

    Falls back to the old timed turn if the robot has not been
    characterised, so it still works out of the box.
    """
    try:
        d = float(degrees)
    except (TypeError, ValueError):
        return
    d = min(max(d, 0), 450)
    if d == 0:
        return

    if not calibrated():
        return _turn_degrees_timed(direction, d)

    import gyro
    # Gyro yaw is positive to the right, so a left turn is a negative target.
    requested = -d if str(direction).lower() == "left" else d
    # Do not apply more compensation than the requested motion itself. That
    # keeps 1-2 degree classroom requests bounded while allowing ordinary
    # turns to land on their requested heading instead of predictably short.
    bias = min(TURN_STOP_BIAS_DEG, d)
    target = requested + (-bias if requested < 0 else bias)

    stop()
    _hold_on(target, 0, spin=True, reverse=False)

    t0 = time.ticks_ms()
    settled = None
    while time.ticks_diff(time.ticks_ms(), t0) < TURN_TIMEOUT_MS:
        if _abort_requested:
            break
        # Honour the controller's own latch: when it has decided it can do
        # no better, waiting out the timeout just holds a motionless robot
        # for five seconds.
        if _settled:
            break
        err = target - gyro.gyro_turn()
        if abs(err) <= TURN_TOL_DEG:
            if settled is None:
                settled = time.ticks_ms()
            elif time.ticks_diff(time.ticks_ms(), settled) >= TURN_HOLD_MS:
                break
        else:
            settled = None
        _sleep_ms(10)

    stop()
    return requested - gyro.gyro_turn()


def _turn_degrees_timed(direction, degrees):
    """The original open-loop turn, kept as the uncalibrated fallback.


    HONEST LIMITS (open-loop, no gyro):
      - accurate roughly 20-180 deg; linear scaling of a single measured point
      - BELOW ~15 deg the launch ramp dominates and it will under-rotate
      - large angles accumulate error; 450 deg is the hard cap
      - battery level and floor surface shift the result
    """
    try:
        d = float(degrees)
    except (TypeError, ValueError):
        d = 0
    d = min(max(d, 0), 450)                 # clamp per the block's range
    if d == 0:
        return
    t90 = None
    try:
        import json
        with open(MAZE_CAL_FILE) as f:
            t90 = json.load(f).get("t90_" + str(direction).lower())
    except (OSError, ValueError, ImportError):
        pass
    if t90 is None:
        print("robot: t90 not calibrated - run bench turn section")
        return
    t = t90 * d / 90.0
    stop()
    turn(direction)
    _sleep_ms(int(t * 1000))
    stop()

def turn90(direction="left"):
    """90-degree spin (kept as its own call; now a thin wrapper)."""
    turn_degrees(direction, 90)

def trim_adjust(wheel="left", percent=2):
    """TEACHER/CAL BLOCK: run ONE wheel at (100 - percent)%, the other at 100%.

    ABSOLUTE, not cumulative: running this twice with 2 does the same thing as
    running it once with 2. The kid raises the number until the robot drives
    straight, then runs 'save trim' once."""
    try:
        p = float(percent)
    except (TypeError, ValueError):
        return get_trim()
    p = min(max(p, 0), 50) / 100.0          # clamp 0-50%
    ch = "A" if (str(wheel).lower() == "left") == (LEFT_MOTOR == "A") else "B"
    if ch == "A":
        set_trim(a=1.0 - p, b=1.0)          # other wheel always back to full
    else:
        set_trim(a=1.0, b=1.0 - p)
    print("trim now A=%.3f B=%.3f" % (_trim["A"], _trim["B"]))
    return get_trim()

def set_trim(a=None, b=None):
    """Set straight-drive trim in RAM. Values clamped to 0.5-1.0."""
    global _trim
    if a is not None:
        _trim["A"] = min(max(float(a), 0.5), 1.0)
    if b is not None:
        _trim["B"] = min(max(float(b), 0.5), 1.0)
    return _trim["A"], _trim["B"]

def get_trim():
    return _trim["A"], _trim["B"]

def save_trim():
    with open(TRIM_FILE, "w") as f:
        f.write(str(_trim["A"]) + "," + str(_trim["B"]))
    print("saved trim:", _trim["A"], _trim["B"])

def os_timer(on):
    """Direct runtime switch, kept for REPL use and tests. Deliberately does
    NOT touch SETTINGS_FILE: apply_settings() + robot_settings.txt is the
    persistent configuration mechanism, this is only a live override."""
    global OS_TIMER
    OS_TIMER = bool(on)
    if OS_TIMER:
        _timer_start()
    else:
        _timer_stop()

def shutdown():
    """Full teardown, matching the handover's verified order."""
    stop()
    servo_off()
    _timer_stop()                   # no-op when OS_TIMER is False
    _oled.fill(0)
    _oled.show()


# ===========================================================================
# CALIBRATION  -  Harrison's method, plus what a real robot taught us
# ===========================================================================

CAL_LOG    = "cal_log.txt"
CAL_STATE_FILE = "mmcal_work.json"
CAL_STATE_VERSION = 2
BREAKAWAY_PROBES = (120, 180, 240, 300, 360, 420, 480, 540, POWER_SAFE_MAX)
CAL_HEALTH_DUTY = 300
CAL_HEALTH_RATE_MIN = 15.0
PROBE_MS   = 300
SPIN_MS    = 450
SETTLE_MS  = 250
N_POINTS   = 5
TM_DEFAULT = 0.18
CAL_ROW    = (OLED_Y0 + 16, OLED_Y0 + 24, OLED_Y0 + 32)
_log_sink  = None


def set_log_sink(callback=None):
    """Mirror calibration diagnostics to a runner-provided callback."""
    global _log_sink
    _log_sink = callback


def _log(line):
    """Eleven readings in eight seconds on a 72x40 screen, while the robot
    spins on the floor, is not a diagnostic. This is."""
    try:
        with open(CAL_LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if _log_sink is not None:
        try:
            _log_sink(line)
        except Exception:
            # Logging must never be allowed to interrupt motor cleanup or
            # invalidate the on-board copy of the calibration record.
            pass


def _cal_show(a="", b="", c=""):
    """Three lines BELOW the dashboard rows.

    characterise() stops the OS timer for its duration -- the dashboard
    repaints every 500ms and clears the screen, so anything written while it
    runs is wiped before it can be read.
    """
    try:
        _oled.fill(0)
        _oled.text("CALIBRATE", OLED_X0, OLED_Y0)
        for txt, y in zip((a, b, c), CAL_ROW):
            if txt:
                _oled.text(txt[:9], OLED_X0, y)
        _oled.show()
    except Exception:
        pass


def _median(values):
    """Median for short MicroPython lists; robust to tile/grout transients."""
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) & 1:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _load_cal_state():
    """Load a valid interrupted-calibration checkpoint, or start cleanly."""
    try:
        import json
        with open(CAL_STATE_FILE) as source:
            state = json.load(source)
        if (not isinstance(state, dict) or
                state.get("schema") != CAL_STATE_VERSION):
            return {}
        return state
    except (OSError, ValueError, TypeError):
        return {}


def _save_cal_state(state):
    """Atomically checkpoint expensive stages without touching live gains."""
    import json, os
    temporary = CAL_STATE_FILE + ".next"
    with open(temporary, "w") as output:
        json.dump(state, output)
    try:
        os.remove(CAL_STATE_FILE)
    except OSError:
        pass
    os.rename(temporary, CAL_STATE_FILE)


def reset_characterisation():
    """Discard only an unfinished calibration; installed working gains stay."""
    import os
    for filename in (CAL_STATE_FILE, CAL_STATE_FILE + ".next"):
        try:
            os.remove(filename)
        except OSError:
            pass


def _cal_guard_clearance(minimum_mm=CAL_CLEARANCE_MM):
    """Abort near a wall; no echo means open space beyond sensor range."""
    if _abort_requested:
        raise RuntimeError("run stopped")
    valid = []
    for _ in range(3):
        distance = _read_ultrasonic_mm()
        if distance >= 0:
            valid.append(distance)
        _sleep_ms(8)
    if len(valid) < 2:
        return NO_ECHO_MM
    distance = int(_median(valid))
    if distance < minimum_mm:
        raise RuntimeError("calibration stopped: front clearance %d mm" % distance)
    return distance


def _wheel_rate(ch, duty, reverse=False, brake_other=True):
    """Measure one wheel at one duty and in one direction.

    Loaded breakaway measurements may brake the opposite wheel. Simple motor
    health checks must coast it: a sustained loaded pivot can trip the driver
    channel and make a healthy motor appear dead until power is removed.
    """
    import gyro
    rates = []
    duty = min(max(int(duty), 0), CAL_POWER_MAX)
    try:
        _cal_guard_clearance()
        _arm_motion_deadline()
        # Brake the other wheel so this is a loaded breakaway test rather
        # than a free-running wheel test.
        if ch == "A":
            other = BRAKE_LEVEL if brake_other else 0
            _pwm["B1"].duty(other)
            _pwm["B2"].duty(other)
            drive, idle = (("A1", "A2") if not FLIP_A else ("A2", "A1"))
        else:
            other = BRAKE_LEVEL if brake_other else 0
            _pwm["A1"].duty(other)
            _pwm["A2"].duty(other)
            drive, idle = (("B2", "B1") if not FLIP_B else ("B1", "B2"))
        if reverse:
            drive, idle = idle, drive
        _pwm[drive].duty(int(duty))
        _pwm[idle].duty(0)
        _sleep_ms(150)
        gyro.gyro_reset()
        last = 0.0
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 400:
            _sleep_ms(LOOP_MS)
            angle = gyro.gyro_turn()
            rates.append(abs(angle - last) * (1000.0 / LOOP_MS))
            last = angle
            if len(rates) % 5 == 0:
                _cal_guard_clearance()
    finally:
        stop()
    _sleep_ms(250)
    if len(rates) < 4:
        return 0.0
    return _median(rates[len(rates) * 2 // 3:])


def _wheel_starts(ch, duty):
    """Does ONE wheel turn unaided in both directions? Returns weaker rate.

    NO KICK. Breakaway is by definition the duty that starts the wheel on
    its own; a launch pulse starts it for you and the measurement then just
    reports the pulse dying away -- that read 60 for a wheel needing 230.
    """
    forward_rate = _wheel_rate(ch, duty, False)
    reverse_rate = _wheel_rate(ch, duty, True)
    _log("  wheel %s %d pair fwd=%.1f rev=%.1f"
         % (ch, duty, forward_rate, reverse_rate))
    # Requiring the weaker direction to pass avoids finding a floor that
    # works going forward but stalls during the opposite turn or reverse.
    return min(forward_rate, reverse_rate)


def _verify_motor_health():
    """Prove both motors work both ways before trusting saved calibration.

    A disconnected wheel can still produce yaw when the other wheel pivots,
    so paired closed-loop turns alone are not a motor-health test. Loaded
    single-wheel rates make an open wire unambiguous and also provide a raw,
    trim-free estimate of the wheel-speed mismatch.
    """
    health = {}
    for ch in ("A", "B"):
        forward_rate = _wheel_rate(ch, CAL_HEALTH_DUTY, False, False)
        reverse_rate = _wheel_rate(ch, CAL_HEALTH_DUTY, True, False)
        health[ch] = {"forward": forward_rate, "reverse": reverse_rate,
                      "typical": _median((forward_rate, reverse_rate))}
        _log("health wheel %s duty %d fwd=%.1f rev=%.1f"
             % (ch, CAL_HEALTH_DUTY, forward_rate, reverse_rate))
        if min(forward_rate, reverse_rate) < CAL_HEALTH_RATE_MIN:
            _log("FAIL wheel %s health below %.1f deg/s"
                 % (ch, CAL_HEALTH_RATE_MIN))
            _cal_show("CAL FAIL", "wheel %s wire?" % ch, "old cal kept")
            return None
    return health


def _trim_from_health(health):
    """Return a conservative raw-rate trim estimate, or None if implausible."""
    a = float(health["A"]["typical"])
    b = float(health["B"]["typical"])
    if min(a, b) < CAL_HEALTH_RATE_MIN:
        return None
    if a >= b:
        candidate = (b / a, 1.0)
    else:
        candidate = (1.0, a / b)
    if min(candidate) < 0.65:
        _log("trim estimate rejected: excessive mismatch A=%.3f B=%.3f"
             % candidate)
        return None
    current = get_trim()
    if (abs(candidate[0] - current[0]) > 0.20 or
            abs(candidate[1] - current[1]) > 0.20):
        _log("trim estimate rejected: jump %s -> %s" % (current, candidate))
        return None
    _log("trim estimate raw rates A=%.1f B=%.1f -> A=%.3f B=%.3f"
         % (a, b, candidate[0], candidate[1]))
    return candidate


def _find_starts():
    """Each wheel's breakaway duty, coarse then fine.

    Replaces bench.run("launch"), which propped the wheels in the air and
    asked a human "did it spin?" in steps of 50 -- and a wheel spinning free
    in the air breaks away lower than one carrying a quarter of the robot.

    It matters twice: it is the launch floor, and it sets the floor for the
    spin sweep. The two wheels do not break away together (one robot: 270
    and 165) and between those figures only the softer wheel turns, so the
    robot PIVOTS about the stiff one. A pivot makes yaw exactly like a spin
    does, so the gyro cannot tell them apart and a sweep starting too low
    characterises half the drivetrain and reports success.
    """
    found = {}
    for ch in ("A", "B"):
        _log("--- wheel %s breakaway ---" % ch)
        coarse = None
        for d in BREAKAWAY_PROBES:
            _cal_show("wheel " + ch, "coarse %d" % d)
            r = _wheel_starts(ch, d)
            _log("  coarse %4d -> %6.1f deg/s" % (d, r))
            if r > 15.0:
                coarse = d
                break
        if coarse is None:
            found[ch] = None
            continue
        fine = coarse
        d = max(60, coarse - 90)
        while d < coarse:
            _cal_show("wheel " + ch, "fine %d" % d)
            r = _wheel_starts(ch, d)
            _log("  fine   %4d -> %6.1f deg/s" % (d, r))
            if r > 15.0:
                fine = d
                break
            d += 15
        found[ch] = fine
        _log("  wheel %s breakaway = %d" % (ch, fine))
    return found


def _spin_rate_one(duty, ms, direction):
    """Steady yaw rate for one spin direction."""
    import gyro
    rates = []
    try:
        _cal_guard_clearance()
        if direction > 0:
            _motors_raw(duty, False, duty, True)
        else:
            _motors_raw(duty, True, duty, False)
        _sleep_ms(120)
        gyro.gyro_reset()
        last = 0.0
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < ms:
            _sleep_ms(LOOP_MS)
            angle = gyro.gyro_turn()
            rates.append(abs(angle - last) * (1000.0 / LOOP_MS))
            last = angle
            if len(rates) % 5 == 0:
                _cal_guard_clearance()
    finally:
        stop()
    _sleep_ms(SETTLE_MS)
    if len(rates) < 4:
        return 0.0
    return _median(rates[len(rates) * 2 // 3:])


def _spin_rate(duty, ms):
    """Robust steady yaw rate averaged across both spin directions.

    No kick: the sweep floor sits above both wheels' breakaway so they start
    unaided. Kicking would spin the robot up before the measurement and
    every duty would read the same.
    """
    clockwise = _spin_rate_one(duty, ms, 1)
    counter = _spin_rate_one(duty, ms, -1)
    combined = _median((clockwise, counter))
    _log("  spin %d pair cw=%.1f ccw=%.1f median=%.1f"
         % (duty, clockwise, counter, combined))
    return combined


def _measure_tm_one(duty, direction):
    """Measure the time constant for one spin direction.

    It cannot come from the gain runs: after a 100ms pulse at 450 the wheels
    are already past target speed, so there is no rise to time and it reads
    as one sample interval -- which produced gains four times too weak.
    """
    import gyro
    gyro.gyro_reset()
    rates = []
    last = 0.0
    t0 = time.ticks_ms()
    try:
        _cal_guard_clearance()
        if direction > 0:
            _motors_raw(duty, False, duty, True)
        else:
            _motors_raw(duty, True, duty, False)
        while time.ticks_diff(time.ticks_ms(), t0) < 500:
            _sleep_ms(LOOP_MS)
            a = gyro.gyro_turn()
            rates.append((time.ticks_diff(time.ticks_ms(), t0),
                          abs(a - last) * (1000.0 / LOOP_MS)))
            last = a
            if len(rates) % 5 == 0:
                _cal_guard_clearance()
    finally:
        stop()
    _sleep_ms(300)
    if len(rates) < 8:
        return None
    tail = rates[len(rates) * 2 // 3:]
    ss = _median([r for _, r in tail])
    if ss < 15.0:
        return None
    smoothed = []
    for index, (tt, rate) in enumerate(rates):
        start = max(0, index - 1)
        end = min(len(rates), index + 2)
        smoothed.append((tt, _median([item[1] for item in rates[start:end]])))
    consecutive = 0
    for tt, r in smoothed:
        if r >= 0.632 * ss:
            consecutive += 1
        else:
            consecutive = 0
        if consecutive >= 2:
            return tt / 1000.0
    return None


def _measure_tm(duty):
    """Robust time constant from unkicked steps in both directions.

    Grout crossings and gearbox asymmetry can distort one rise. Combining
    both directions makes the controller tuning much less dependent on the
    exact patch of floor used for calibration.
    """
    clockwise = _measure_tm_one(duty, 1)
    counter = _measure_tm_one(duty, -1)
    valid = [value for value in (clockwise, counter) if value is not None]
    result = _median(valid) if valid else None
    _log("  timing pair cw=%s ccw=%s median=%s"
         % (clockwise, counter, result))
    return result


def _validate_characterisation(trim_candidate=None):
    """Validate and gently tune the controller the BIPES blocks actually use.

    A fresh robot still needs characterise(restart=True) for plant
    identification. Once gains exist, normal classroom calibration uses paired
    closed-loop turns instead of a long open-loop sweep that grout and battery
    sag can corrupt. Every left turn is immediately unwound by a right turn.
    """
    global TURN_STOP_BIAS_DEG
    corrections = []
    requested = 30.0
    for index in range(3):
        _cal_guard_clearance()
        _cal_show("validating", "%d of 3" % (index + 1), "left/right")
        left = float(turn_degrees("left", requested))
        _sleep_ms(200)
        right = float(turn_degrees("right", requested))
        _sleep_ms(250)
        # Positive means under-turn in the direction of travel.
        corrections.extend((-left, right))
        _log("validate %d left_res=%.2f right_res=%.2f"
             % (index + 1, left, right))

    adjustment = _median(corrections)
    # One grout seam must not move a good calibration far in one run.
    adjustment = min(max(adjustment, -1.5), 1.5)
    previous_bias = TURN_STOP_BIAS_DEG
    candidate = min(max(previous_bias + adjustment, 0.0), 6.0)
    TURN_STOP_BIAS_DEG = candidate
    _log("turn bias %.2f + %.2f -> %.2f"
         % (previous_bias, adjustment, candidate))

    # Independently confirm the proposed bias before it reaches flash.
    _cal_guard_clearance()
    left = float(turn_degrees("left", requested))
    _sleep_ms(200)
    right = float(turn_degrees("right", requested))
    _sleep_ms(250)
    _log("confirm left_res=%.2f right_res=%.2f" % (left, right))
    if abs(left) > TURN_TOL_DEG or abs(right) > TURN_TOL_DEG:
        TURN_STOP_BIAS_DEG = previous_bias
        _log("FAIL validation outside %.1f degree tolerance" % TURN_TOL_DEG)
        _cal_show("CAL FAIL", "turn verify", "old cal kept")
        return None

    try:
        import json
        with open(MMCAL_FILE, "w") as output:
            json.dump({"Km": _km, "Tm": _tm, "deadband": _dead,
                       "kP": _kp, "kD": _kd,
                       "turn_bias": TURN_STOP_BIAS_DEG}, output)
    except Exception as error:
        TURN_STOP_BIAS_DEG = previous_bias
        _log("FAIL could not save validated gains: %s" % error)
        return None
    if trim_candidate is not None:
        previous_trim = get_trim()
        try:
            set_trim(*trim_candidate)
            save_trim()
            try:
                with open(MAZE_CAL_FILE) as source:
                    maze = json.load(source)
            except (OSError, ValueError):
                maze = {}
            maze["trim"] = {"A": get_trim()[0], "B": get_trim()[1]}
            with open(MAZE_CAL_FILE, "w") as output:
                json.dump(maze, output)
            _log("saved health trim A=%.3f B=%.3f" % get_trim())
        except Exception as error:
            set_trim(*previous_trim)
            _log("trim save failed; previous trim retained: %s" % error)
    _log("OK validated existing gains; turn bias %.2f" % TURN_STOP_BIAS_DEG)
    _cal_show("CAL DONE", "turn %.1f" % TURN_STOP_BIAS_DEG, "gains kept")
    return (_km, _tm, _dead, _kp, _kd)


def characterise(verbose=True, restart=False):
    """Measure this robot and derive its control gains. Once per robot.

    Spins on the spot: needs no room to travel, and both wheels roll rather
    than one scrubbing sideways.
    """
    # Any exception goes to the console, which cannot be read with the robot
    # on the floor and unplugged. A log that simply stops mid-run is
    # indistinguishable from a hang, so catch it and write it down.
    if restart:
        reset_characterisation()
    try:
        result = (_characterise(verbose, force_starts=True) if restart
                  else _characterise(verbose))
        # Leave CAL DONE/FAIL visible long enough to read, then restore the
        # normal distance dashboard. Logs and the return value retain the
        # detailed figures for BIPES/DevLink.
        _sleep_ms(1500)
        return result
    except Exception as e:
        try:
            import sys, io
            buf = io.StringIO()
            sys.print_exception(e, buf)
            _log("CRASH:\n" + buf.getvalue())
        except Exception:
            _log("CRASH: %s: %s" % (type(e).__name__, e))
        _cal_show("CAL CRASH", "see log")
        try:
            stop()
        except Exception:
            pass
        _sleep_ms(1500)
        return None
    finally:
        # _characterise() pauses Timer 0 before its first clearance check and
        # has several legitimate early returns. Every one must restore the
        # dashboard when normal OS mode is enabled; otherwise the OLED and
        # background ultrasonic/ToF sampling appear to have died.
        if OS_TIMER:
            _timer_start()


def _characterise(verbose=True, force_starts=False):
    global _km, _tm, _dead, _kp, _kd, _spin_dead, MAX_DIFF, _gyro_bus_lock
    import gyro

    # Calibration may be launched immediately after a continuous movement
    # block. Merely releasing the gyro callback leaves its last PWM command
    # active and corrupts the stationary zero-rate measurement.
    stop()
    _timer_stop()       # the dashboard would wipe every message

    # Do not reposition the sensor here. Calibration must not surprise a
    # student by moving a newly mounted servo; point it ahead beforehand.
    _cal_guard_clearance(250)

    try:
        with open(CAL_LOG, "w") as f:
            f.write("CAL robot v%s  gyro v%s\n"
                    % (VERSION, getattr(gyro, "VERSION", "OLD - did not land")))
            f.write("gyro range +/-%d deg/s\n" % int(gyro.full_scale()))
            f.write("FLIP_A=%s FLIP_B=%s LEFT=%s\n"
                    % (FLIP_A, FLIP_B, LEFT_MOTOR))
    except OSError:
        pass

    _cal_show("gyro zero", "hold still")
    gyro.gyro_setup(i2c=_i2c)      # share robot's bus, do not make a second
    _gyro_bus_lock = gyro.gyro_bus()
    _sleep_ms(800)

    state = _load_cal_state()
    if calibrated() and not force_starts and not state:
        health = _verify_motor_health()
        if health is None:
            return None
        return _validate_characterisation(_trim_from_health(health))
    saved_starts = state.get("starts")
    reused_starts = False
    if (isinstance(saved_starts, dict) and
            saved_starts.get("A") is not None and
            saved_starts.get("B") is not None):
        starts = {"A": int(saved_starts["A"]), "B": int(saved_starts["B"])}
        reused_starts = True
        _log("RESUME wheel starts A=%s B=%s" % (starts["A"], starts["B"]))
    elif (not force_starts and _breakaway.get("A", 0) > 0 and
          _breakaway.get("B", 0) > 0):
        # These values were already proven by prior commissioning and are
        # used successfully by every live turn. Repeating the loaded
        # one-wheel test on grout can falsely report a stalled motor because
        # the opposing wheel is deliberately braked. Normal calibration
        # reuses the proven values; restart=True explicitly remeasures them.
        starts = {"A": int(_breakaway["A"]), "B": int(_breakaway["B"])}
        reused_starts = True
        _log("REUSE proven wheel starts A=%s B=%s" %
             (starts["A"], starts["B"]))
    else:
        starts = _find_starts()
    if reused_starts and _verify_motor_health() is None:
        return None
    _log("wheel starts A=%s B=%s" % (starts["A"], starts["B"]))
    if starts["A"] is None or starts["B"] is None:
        ch = "A" if starts["A"] is None else "B"
        _log("FAIL wheel %s never turned" % ch)
        _cal_show("CAL FAIL", "wheel %s" % ch, "see log")
        return None

    if not state:
        state = {"schema": CAL_STATE_VERSION}
    state["starts"] = starts
    _save_cal_state(state)

    set_breakaway(starts["A"], starts["B"])
    _spin_dead = float(max(starts["A"], starts["B"]))
    floor = int(_spin_dead * 1.10)
    _log("sweep floor %d (both wheels turning above this)" % floor)
    if floor > CAL_POWER_MAX - 40:
        _log("FAIL safe calibration cap %d is too close to floor %d"
             % (CAL_POWER_MAX, floor))
        _cal_show("CAL FAIL", "high friction", "see log")
        reset_characterisation()
        return None

    # Climb from the floor in 12% steps. A fixed list can step straight from
    # "nothing" to "clipping" with nothing usable between.
    sweep = state.get("sweep")
    if (not isinstance(sweep, list) or len(sweep) != N_POINTS or
            any(not isinstance(value, (int, float)) or value < 0 or
                value > CAL_POWER_MAX for value in sweep)):
        lo = hi = clip = None
        probe = state.get("probe")
        if not isinstance(probe, list):
            probe = []
        for duty, rate in probe:
            if rate >= SAT_LIMIT:
                clip = duty
                break
            if lo is None and rate > 15.0:
                lo = duty
            hi = duty
        d = int(state.get("next_probe", floor))
        if probe:
            _log("RESUME %d completed probe pairs" % len(probe))
        while d <= CAL_POWER_MAX and clip is None:
            _cal_show("probing", "duty %d" % d)
            r = _spin_rate(d, PROBE_MS)
            _cal_show("probing", "duty %d" % d, "%d deg/s" % int(r))
            _log("probe %4d -> %7.1f deg/s" % (d, r))
            probe.append((d, r))
            if r >= SAT_LIMIT:
                clip = d
            else:
                if lo is None and r > 15.0:
                    lo = d
                hi = d
            d = int(d * 1.12) + 1
            state["probe"] = probe
            state["next_probe"] = d
            _save_cal_state(state)

        if lo is None:
            # The first duty at which both wheels turn already clips. The band
            # is between the floor and there, not down near zero.
            lo = floor
            hi = int((clip or min(CAL_POWER_MAX, int(floor * 1.3))) * 0.92)
            if hi <= lo:
                hi = lo + 25
        elif hi is None or hi <= lo:
            hi = int((clip or min(CAL_POWER_MAX, int(lo * 1.3))) * 0.92)
            if hi <= lo:
                hi = lo + 30

        hi = min(hi, CAL_POWER_MAX)
        step = (hi - lo) / float(N_POINTS - 1)
        sweep = [int(lo + step * i) for i in range(N_POINTS)]
        state["sweep"] = sweep
        state["points"] = []
        state["sweep_index"] = 0
        _save_cal_state(state)
        _log("band lo=%s hi=%s clip=%s" % (lo, hi, clip))
        _log("sweep %s" % (sweep,))
    else:
        _log("RESUME sweep %s" % (sweep,))

    pts = state.get("points")
    if not isinstance(pts, list):
        pts = []
    start_index = min(max(int(state.get("sweep_index", 0)), 0), len(sweep))
    for index in range(start_index, len(sweep)):
        duty = sweep[index]
        _cal_show("measuring", "%d of %d" % (index + 1, len(sweep)),
                  "duty %d" % duty)
        ss = _spin_rate(duty, SPIN_MS)
        _log("meas  %4d -> %7.1f deg/s" % (duty, ss))
        if ss > 5.0:
            pts.append((duty, ss))
        state["points"] = pts
        state["sweep_index"] = index + 1
        _save_cal_state(state)
        if ss >= SAT_LIMIT:
            state["sweep_index"] = len(sweep)
            _save_cal_state(state)
            break

    if len(pts) < 3:
        _log("FAIL only %d of %d points moved" % (len(pts), len(sweep)))
        _cal_show("CAL FAIL", "%d/%d pts" % (len(pts), len(sweep)), "see log")
        reset_characterisation()
        return None

    m = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts); sxx = sum(p[0] * p[0] for p in pts)
    den = m * sxx - sx * sx
    if den == 0:
        _cal_show("CAL FAIL", "bad fit", "see log")
        reset_characterisation()
        return None
    km = (m * sxy - sx * sy) / den
    if km <= 0:
        _log("FAIL negative gain - readings clipping")
        _cal_show("CAL FAIL", "clipping", "see log")
        reset_characterisation()
        return None
    dead = -((sy - km * sx) / m) / km

    # A negative intercept is not a failure: it means the motors snap on
    # rather than ramping from a loss offset. One robot went 0 -> 575 deg/s
    # in 28 duty counts, then gained 200 over the next 129, so a straight
    # line through the measured region extrapolates past zero. The measured
    # breakaway is used for turning anyway; this is only the forward figure.
    if dead < 0:
        _log("intercept %.0f negative (motors snap on) - clamped to 0" % dead)
        dead = 0.0

    tm = state.get("tm")
    if tm is None:
        _cal_show("timing", "duty %d" % sweep[-1])
        tm = _measure_tm(sweep[-1])
        if tm is None or tm < 0.03:
            tm = TM_DEFAULT
            _log("Tm not measurable unkicked - using default %.2f" % tm)
        state["tm"] = tm
        _save_cal_state(state)
    else:
        tm = float(tm)
        _log("RESUME timing Tm=%.3f" % tm)

    # Gains from the measured plant. Plant Km/(s(1+Tm.s)) under PD gives
    # s^2 + ((1+Km.Kd)/Tm)s + Km.Kp/Tm = 0; matched to s^2 + 2.zeta.wn.s +
    # wn^2 with wn = 4/(zeta.tds). Reproduces Harrison's published example
    # (Km=142, Tm=0.165 -> kP 7.8, kD 0.126) to three figures.
    wn = 4.0 / (ZETA * TDS)
    kp = wn * wn * tm / km
    kd = (2 * ZETA * wn * tm - 1) / km
    if kd < 0:
        kd = 0.0

    _km, _tm, _dead, _kp, _kd = km, tm, dead, kp, kd
    MAX_DIFF = int(min(max(dead, _spin_dead * 0.7) + TURN_RATE_MAX / km, 1023))

    try:
        import json
        with open(MMCAL_FILE, "w") as f:
            json.dump({"Km": km, "Tm": tm, "deadband": dead,
                       "kP": kp, "kD": kd,
                       "turn_bias": TURN_STOP_BIAS_DEG}, f)
        try:
            with open(MAZE_CAL_FILE) as f:
                c = json.load(f)
        except (OSError, ValueError):
            c = {}
        c["breakaway_A"] = starts["A"]
        c["breakaway_B"] = starts["B"]
        with open(MAZE_CAL_FILE, "w") as f:
            json.dump(c, f)
    except Exception as e:
        _log("could not save: %s" % e)
        return None

    reset_characterisation()

    _log("OK Km=%.4f Tm=%.3f deadband=%.0f kP=%.2f kD=%.4f MAX_DIFF=%d"
         % (km, tm, dead, kp, kd, MAX_DIFF))
    # The public wrapper leaves this visible briefly and then restores the
    # distance dashboard. The complete numbers are also saved and logged.
    _cal_show("CAL DONE", "Km %.2f" % km, "dz %d" % int(_spin_dead))
    return (km, tm, dead, kp, kd)


# Last: every function above must exist before this runs, and module-level
# code executes in order. Putting it with the other _load_*() calls near the
# top fails with NameError.
_load_mmcal()
