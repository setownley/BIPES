# robot.py — classroom runtime for ESP32-C3 Super Mini robot (01Space OLED variant)
# Deploy to the board's flash root:  mpremote cp robot.py :
# Every BIPES custom block compiles to a one-line call into this module.
#
# HARD RULE FOR THIS FILE: this module is the ONLY code that ever touches
# Timer 0, the sensors, or the OLED. Student-generated code must only call
# the public functions at the bottom.

VERSION = "0.7.1"  # gyro closed-loop steering and turns + merged-back servo/ping (0.6.2)

from machine import Pin, I2C, Timer, PWM, ADC, time_pulse_us
import time
import ssd1306

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
PIN_SERVO = 20        # SG90 signal. GPIO20 is U0RXD, so it is an input during
                      # the ROM boot log and the servo will not twitch at reset.

# Servo tuning ---------------------------------------------------------------
SERVO_MIN_US   = 500      # pulse width at 0 degrees
SERVO_MAX_US   = 2400     # pulse width at 180 degrees
SERVO_FREQ     = 50       # Hz. Servos want 50; motors run at PWM_FREQ=1000.
SERVO_SETTLE_MS = 350     # time for the horn to actually arrive and stop
                          # swinging. Measured, not guessed: pinging before
                          # this is up gives a reading from wherever the
                          # sensor happened to be mid-swing, which looks like
                          # a flaky sensor rather than a timing bug.

# Where the sensor is actually pointing at each named position. Set these to
# suit how the servo is mounted on YOUR chassis -- if left and right come out
# swapped, swap these two numbers rather than rewiring anything.
SERVO_LEFT   = 180
SERVO_AHEAD  = 90
SERVO_RIGHT  = 0

# Teacher tuning knobs -------------------------------------------------------
ECHO_TIMEOUT_US = 12000     # max range = 12000 * 100 // 582 = 2061 mm (~2.06 m)
NO_ECHO_MM      = 9999      # returned by distance_mm()/side_mm() when no valid reading
TOF_MAX_VALID_MM = 2200     # VL53L0X raw reads above this = out-of-range (family ceiling ~2 m)
PWM_FREQ        = 1000      # Hz — matches bench-tested exploratory firmware
SPEEDS = {"slow": 600, "medium": 800, "fast": 1023}   # .duty() 0-1023; MEASURED on chassis #1 floor test 2026-07-07 (was placeholder 400/700)
LEFT_MOTOR = "A"            # which DRV8833 channel drives the LEFT wheel
FLIP_A = False              # set True if motor A runs backwards for "forward"
FLIP_B = True   # motor B wiring reversed on this chassis - bench-determined 2026-07-07
TICK_MS = 100               # sensor sampling period

# --- gyro closed-loop steering (Harrison method, micromouseonline.com) ----
MMCAL_FILE = "mmcal.json"
ZETA = 0.7          # slightly underdamped: a couple of percent overshoot
TDS  = 0.25         # settling time. Harrison uses 0.070 sampling at 1ms;
                    # the gyro here samples at 20ms, where 0.070 is four
                    # samples and the discrete loop is unstable. 0.25 gives
                    # about twelve.
LOOP_MS  = 20       # gyro sampler period - the steering rate
GYRO_MAX_DPS = 250.0    # MPU-6050 default full scale
SAT_LIMIT    = 200.0    # keep spin rate below this so the gyro never clips
MAX_DIFF = 400      # cap on the steering correction. Recomputed from the
                    # measured plant by characterise() -- see below. The
                    # value matters more than it looks: at full correction a
                    # 110mm robot can spin faster than the MPU-6050's
                    # +/-250 deg/s range, at which point the reading wraps,
                    # the controller chases a bogus angle and the turn runs
                    # away. A 180 degree turn overshot to 1300 degrees
                    # before this was derived rather than guessed.

_km = _tm = _dead = _kp = _kd = 0.0      # measured plant; 0 = uncalibrated
_hold = False       # heading loop active?
_target = 0.0       # heading being held, degrees
_base = 0           # forward duty being steered around; 0 = spin on the spot
_err_old = 0.0
RAMP_MS = 200               # soft-start: motor duty ramps to target over this
RAMP_STEPS = 10             # ... in this many steps (stop() is always instant)
BRAKE_MS = 300              # stop(): active brake (both inputs high) before coast
LAUNCH_HOLD_MS = 100        # standstill launch: hold at breakaway before ramping
CAL_GATE_MS = 3000          # kid self-cal: TAP=CAL window at program start
GAME_HOLD_MS = 10000        # hold BOOT for 10s at cal gate to launch Arcade
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
MAZE_ADVANCE_MM = 230       # parks the PIVOT at gap center: 120 (sensor->axle) + 150 (half gap) - ~40 (debounce travel)
MAZE_GAP_MM = 450           # 1.5 cells with no wall = treat as open
MAZE_SPEED = "slow"         # 290 mm/s: 29 mm/tick staleness
NUDGE_SLOW = 0.55           # nudged wheel runs at this fraction of the other
# Nudge rate: seconds of nudging per degree of heading change, ESTIMATED from
# the track width (160 mm), NUDGE_SLOW and the measured medium speed - NOT
# measured. Expect the real angle to be within roughly a factor of 2. Deliberate
# choice: nudge is a "bend a bit" tool, not a precision instrument. Tune this
# ONE number if the class wants nudges closer to the stated angle.
NUDGE_S_PER_DEG = 0.017
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

_trig = Pin(PIN_TRIG, Pin.OUT)
_trig.value(0)
_echo = Pin(PIN_ECHO, Pin.IN)

_servo = PWM(Pin(PIN_SERVO))
_servo.freq(SERVO_FREQ)
_servo_angle = None       # None = never commanded, so the first move always
                          # waits the full settle time

_ping_busy = False        # the background tick also pings. Both drive TRIG
                          # and read ECHO, so an overlap gives one of them a
                          # nonsense reading. This flag makes the loser skip
                          # rather than interleave.

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
        pass                      # defaults 1.0/1.0

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

def _read_ultrasonic_mm():
    # Per verified handover firmware. time_pulse_us RETURNS -1/-2 on timeout
    # on this MicroPython (>=1.14); it does not raise.
    _trig.value(0)
    time.sleep_us(5)
    _trig.value(1)
    time.sleep_us(10)
    _trig.value(0)
    return time_pulse_us(_echo, 1, ECHO_TIMEOUT_US) * 100 // 582

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
    # 12 ms no-echo timeout + ~25 ms OLED repaint = ~37 ms inside 100 ms.
    global _dist_mm, _side_mm, _qre_raw, _tick, _ping_busy
    if not _ping_busy:
        _dist_mm = _read_ultrasonic_mm()
    _qre_raw = _read_qre_avg(5)
    if _tof:
        try:
            if _tof.reading_available():
                _v = _tof.get_range_value()
                _side_mm = _v if (_v is not None and _v <= TOF_MAX_VALID_MM) else -1
                _tof.start_range_request()      # immediately begin next measure
            elif not _tof.range_started:
                _tof.start_range_request()      # first tick after import
        except OSError:
            _side_mm = -1
    _tick += 1
    if _tick % OLED_EVERY_N_TICKS == 0:
        _repaint()

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
def _apply(target):
    # Soft start: ramp all four channels together from current to target.
    # Reduces the stiction/torque-mismatch lurch when trims differ (v0.3.1).
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
        time.sleep_ms(LAUNCH_HOLD_MS)
    for i in range(1, RAMP_STEPS + 1):
        for k in _pwm:
            _pwm[k].duty(start[k] + (target[k] - start[k]) * i // RAMP_STEPS)
        time.sleep_ms(RAMP_MS // RAMP_STEPS)

def _motors(duty_a, rev_a, duty_b, rev_b):
    target = {"A1": 0, "A2": 0, "B1": 0, "B2": 0}
    def _ch(ch, duty, reverse):
        a, b = (ch + "1", ch + "2")
        if reverse:
            a, b = b, a
        target[a] = int(duty * _trim[ch])
        target[b] = 0
    _ch("A", duty_a, rev_a != FLIP_A)
    _ch("B", duty_b, rev_b != FLIP_B)
    _apply(target)

def _motors_raw(duty_a, rev_a, duty_b, rev_b):
    """Set duty immediately: no trim, no ramp.

    The closed loop must drive the hardware directly. Trim exists to correct
    the motor mismatch open-loop, and applying it underneath a controller
    already correcting that same mismatch means the two fight each other.
    The ramp would add lag the derivative term reads as noise.
    """
    def _raw(ch, duty, reverse):
        a, b = (ch + "1", ch + "2")
        if reverse:
            a, b = b, a
        _pwm[a].duty(int(duty))
        _pwm[b].duty(0)
    _raw("A", duty_a, rev_a != FLIP_A)
    _raw("B", duty_b, rev_b != FLIP_B)


def _steer_heading(angle):
    """One PD step, called from the gyro sampler at 50Hz.

    NOT named _steer: robot.py already has a _steer(err_mm) for wall
    following, defined further down. Two functions of the same name means
    the later one silently wins, and the gyro ends up calling the wall
    follower with an angle. That cost an hour once.

    Harrison's parallel form:
        errorOld = error;
        error = setPos - currentPos;
        PWM   = kP * error;
        PWM  += kD * (error - errorOld);

    Runs in a timer callback, so no I2C, no sleeps, no allocation beyond
    locals -- the sampler is due again in 20ms.
    """
    global _err_old
    if not _hold:
        return

    err = _target - angle
    diff = _kp * err + _kd * (err - _err_old) * (1000.0 / LOOP_MS)
    _err_old = err

    # Below the deadband the motors do nothing at all, so a small demand is
    # simply ignored and the error sits there unfixed. Lift it over the
    # threshold: this is what the intercept from the fit is for.
    if diff > 1:
        diff += _dead
    elif diff < -1:
        diff -= _dead

    if diff > MAX_DIFF:
        diff = MAX_DIFF
    elif diff < -MAX_DIFF:
        diff = -MAX_DIFF

    if _base == 0:
        # Spinning: SAME magnitude both wheels, opposite directions.
        # Deriving each wheel's sign separately does not work - one comes out
        # negative, its reverse flag reads False, and the robot drives away
        # in a straight line instead of turning.
        mag = int(min(abs(diff), 1023))
        _motors_raw(mag, diff < 0, mag, diff > 0)
    else:
        da = _base + diff
        db = _base - diff
        _motors_raw(int(min(max(da, 0), 1023)), False,
                    int(min(max(db, 0), 1023)), False)


def _hold_on(target, base):
    global _hold, _target, _base, _err_old
    import gyro
    gyro.gyro_setup()
    gyro.gyro_reset()
    _target = target
    _base = base
    _err_old = target
    _hold = True
    gyro.gyro_callback(_steer_heading)


def _hold_off():
    global _hold
    _hold = False
    try:
        import gyro
        gyro.gyro_callback(None)
    except Exception:
        pass


def calibrated():
    """True once characterise() has been run on this robot."""
    return _km > 0 and _kp > 0


def _load_mmcal():
    global _km, _tm, _dead, _kp, _kd
    try:
        import json
        with open(MMCAL_FILE) as f:
            c = json.load(f)
        _km = float(c.get("Km", 0)); _tm = float(c.get("Tm", 0))
        _dead = float(c.get("deadband", 0))
        _kp = float(c.get("kP", 0)); _kd = float(c.get("kD", 0))
        if _km > 0:
            global MAX_DIFF
            MAX_DIFF = int(min(_dead + SAT_LIMIT / _km, 1023))
        return True
    except (OSError, ValueError, ImportError, TypeError):
        return False


# Called here rather than with the other _load_*() calls near the top: those
# run before this function is defined, and module-level code runs in order.
_load_mmcal()


def _speed(name):
    return SPEEDS.get(str(name).lower(), SPEEDS["medium"])

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

def forward(speed="medium"):
    """Drive forward, holding the heading it started on.

    Same signature and same immediate return as before, so every existing
    block and program is unchanged. The difference is that the gyro sampler
    now steers in the background until stop() is called.

    Uncalibrated, it falls back to the old open-loop behaviour rather than
    driving with meaningless gains.
    """
    global _cur_speed
    _cur_speed = speed
    d = _speed(speed)
    if not calibrated():
        _motors(d, False, d, False)
        return
    _hold_on(0.0, d)

def forward_at(duty):
    """Drive forward at a specific PWM duty, 0 to 1023 (clamped), instead of
    a named speed. Goes through the same _motors() path as forward() did
    before closed-loop steering, so per-wheel trim and the soft-start ramp
    in _apply() still apply.

    Deliberately open-loop, unlike forward(): does not engage _hold_on(),
    so it does not touch _cur_speed or the heading-hold state. nudge() keeps
    resuming whatever NAMED speed forward() last set, not a raw duty number.

    There is a launch-floor mechanism (see _apply()/_breakaway): below
    roughly 600 on this chassis, static friction can mean the wheels do
    not turn at all even though the PWM signal is real.
    """
    try:
        d = int(duty)
    except (TypeError, ValueError):
        return
    d = min(max(d, 0), 1023)
    _motors(d, False, d, False)

def backward(speed="medium"):
    """Open loop, deliberately.

    Reversing under gyro control needs the correction sign flipped, and that
    is a different enough behaviour to want its own testing. Left as it was
    rather than changed untested.
    """
    _motors(_speed(speed), True, _speed(speed), True)

def turn(direction="left"):
    # spin turn in place at medium speed
    d = _speed("medium")
    if str(direction).lower() == "left":
        left_rev, right_rev = True, False
    else:
        left_rev, right_rev = False, True
    if LEFT_MOTOR == "A":
        _motors(d, left_rev, d, right_rev)
    else:
        _motors(d, right_rev, d, left_rev)

def stop():
    # Release the heading loop BEFORE braking. Left running, it would see the
    # robot stop, read a growing error and fight the brake.
    _hold_off()
    # v0.3.2: brake first (DRV8833 HIGH/HIGH = windings shorted, symmetric,
    # hard stop - kills the asymmetric coast yaw), then release to coast.
    # Applied INSTANTLY - no ramp on the safety path.
    for p in _pwm.values():
        p.duty(1023)
    time.sleep_ms(BRAKE_MS)
    for p in _pwm.values():
        p.duty(0)           # coast (DRV8833 LOW/LOW), original safe state

def wait(seconds):
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        s = 0
    time.sleep(min(max(s, 0), 60))   # clamp 0-60 s

def distance_mm():
    return _dist_mm if _dist_mm >= 0 else NO_ECHO_MM

def servo(angle):
    """Point the servo at an angle, 0 to 180 degrees.

    Returns straight away. The horn takes about SERVO_SETTLE_MS to arrive,
    so use look() if you are about to measure.
    """
    global _servo_angle
    try:
        a = float(angle)
    except (TypeError, ValueError):
        return
    a = min(max(a, 0), 180)
    us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * a / 180.0
    # duty_u16 rather than duty(): 10-bit gives only 97 steps across the
    # whole sweep, which is 1.9 degrees per step and visibly notchy.
    _servo.duty_u16(int(65535 * us / (1000000.0 / SERVO_FREQ)))
    _servo_angle = a

def look(where):
    """Point the sensor and WAIT for it to get there.

    where: 'left', 'ahead', 'right', or a number of degrees.

    Waits only as long as the move needs -- a 5 degree nudge does not cost
    the same as a full sweep. Use this before measuring; use servo() if you
    do not care when it arrives.
    """
    global _servo_angle
    if where == 'left':
        a = SERVO_LEFT
    elif where == 'right':
        a = SERVO_RIGHT
    elif where == 'ahead' or where == 'centre' or where == 'center':
        a = SERVO_AHEAD
    else:
        try:
            a = min(max(float(where), 0), 180)
        except (TypeError, ValueError):
            return

    was = _servo_angle
    servo(a)
    if was is None:
        time.sleep_ms(SERVO_SETTLE_MS)
    else:
        # Scale the wait to how far it actually has to travel.
        frac = abs(a - was) / 180.0
        time.sleep_ms(int(60 + (SERVO_SETTLE_MS - 60) * frac))

def servo_off():
    """Stop driving the servo so it goes limp and quiet.

    A servo holding position draws current and often buzzes. Worth doing
    when the robot has finished scanning.
    """
    _servo.duty_u16(0)

def ping_mm(timeout_ms=None):
    """Measure the distance ahead RIGHT NOW, in millimetres.

    distance_mm() gives the last reading the background tick took, which can
    be up to half a second old -- fine for a dashboard, useless for deciding
    whether to stop. This one measures when you call it.

    timeout_ms: how long to wait for an echo. Leave it out for the standard
    12 ms, which reaches about 2 metres. Shorter is faster but sees less:
    the sound has to get there and back, so 6 ms only reaches about a metre.

    Returns NO_ECHO_MM (9999) if nothing came back.
    """
    global _ping_busy

    if timeout_ms is None:
        t_us = ECHO_TIMEOUT_US
    else:
        try:
            t_us = int(float(timeout_ms) * 1000)
        except (TypeError, ValueError):
            t_us = ECHO_TIMEOUT_US
        t_us = min(max(t_us, 1000), 30000)     # 1-30 ms, ~17 cm to ~5 m

    if _ping_busy:                 # the background tick has the sensor
        return distance_mm()

    _ping_busy = True
    try:
        _trig.value(0)
        time.sleep_us(5)
        _trig.value(1)
        time.sleep_us(10)
        _trig.value(0)
        raw = time_pulse_us(_echo, 1, t_us)
    finally:
        _ping_busy = False

    if raw < 0:                    # -1 / -2 mean timeout on this port
        return NO_ECHO_MM
    return raw * 100 // 582

def look_and_measure(where, timeout_ms=None):
    """Point the sensor, wait for it to settle, then measure. One block.

    This pairing is the whole reason the servo is on the robot, and doing it
    in two steps is where students trip up -- measuring before the horn has
    stopped moving gives a reading from halfway through the sweep.
    """
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
        time.sleep_ms(20)
    p0 = time.ticks_ms()
    while _btn.value() == 0:
        time.sleep_ms(20)
        if time.ticks_diff(time.ticks_ms(), p0) >= 2000:
            break
    return 'hold' if time.ticks_diff(time.ticks_ms(), p0) >= 600 else 'tap'

def _cal_pass():
    """One forward wall run. Returns list of (i, side_mm) samples or None."""
    raw = []
    forward('medium')
    try:
        for i in range(20):
            time.sleep_ms(100)
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

def _play_game():
    """Teacher easter egg: hand the board to the Arcade menu.

    The robot background timer must be stopped because the arcade and games
    own the OLED while running. Press RST to reboot normally.
    """
    stop()                         # motors safe before entering the game
    _timer_stop()                  # prevent sensor/dashboard OLED interference
    import arcade
    arcade.run(_oled, _btn, OLED_X0, OLED_Y0, _led)


def cal_gate():
    """Prepended to every student program by BIPES Save-to-robot.

    Normal behaviour is unchanged:
      - no BOOT press within 3s -> run the student program
      - tap/release BOOT -> kid self-cal, then halt

    Hidden teacher/game behaviour:
      - press BOOT during the 3s window and KEEP holding it
      - after 2s the OLED shows a countdown
      - at 10s Arcade launches
    """
    show("TAP=CAL")

    # Wait up to the normal 3-second gate for the INITIAL press.
    t0 = time.ticks_ms()
    while _btn.value() == 1:
        if time.ticks_diff(time.ticks_ms(), t0) >= CAL_GATE_MS:
            show("")
            return
        time.sleep_ms(20)

    # BOOT is down. A normal release means calibration; a 10-second hold
    # launches the hidden game. The countdown begins after 2 seconds so an
    # ordinary calibration tap still feels exactly as it did before.
    p0 = time.ticks_ms()
    last_count = None
    while _btn.value() == 0:
        held = time.ticks_diff(time.ticks_ms(), p0)

        if held >= GAME_HOLD_MS:
            _play_game()           # does not return

        if held >= 2000:
            remaining = (GAME_HOLD_MS - held + 999) // 1000
            if remaining != last_count:
                last_count = remaining
                show("GAME IN %d" % remaining)

        time.sleep_ms(50)

    # Released before 10 seconds -> normal self-calibration path.
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
    flip = FLIP_A if ch == "A" else FLIP_B
    a, b = ((ch + "2", ch + "1") if flip else (ch + "1", ch + "2"))
    _pwm[a].duty(int(duty))
    _pwm[b].duty(0)

def get_breakaway():
    return _breakaway["A"], _breakaway["B"]

def set_breakaway(a, b):
    """Set launch floors in RAM (bench launchtune). Clamped 0-1023."""
    _breakaway["A"] = min(max(int(a), 0), 1023)
    _breakaway["B"] = min(max(int(b), 0), 1023)
    return _breakaway["A"], _breakaway["B"]

def raw_forward(duty):
    """Teacher/bench only: forward at a fixed raw duty (trimmed, NO ramp)."""
    d = int(duty)
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
    global _last_event
    base = _speed(MAZE_SPEED)
    mm_per_tick = 29                      # slow, measured 290 mm/s
    if distance_mm() < MAZE_FRONT_STOP_MM:
        _last_event = "front"             # v0.5.1: pre-check BEFORE moving -
        return                            # dead-end second turn fires with zero motion
    forward(MAZE_SPEED)                   # ramped launch
    open_ticks = 0
    gap_mm = 0
    prev_s = None
    try:
        while True:
            time.sleep_ms(TICK_MS)
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
                        time.sleep_ms(TICK_MS)
                        if distance_mm() < MAZE_FRONT_STOP_MM:
                            _last_event = "front"
                            return
                        adv -= mm_per_tick
                    _last_event = "left"
                    return
                if gap_mm >= MAZE_GAP_MM:
                    _last_event = "left"
                    return
                _steer(base, 0)           # hold straight across small gaps
            else:
                open_ticks = 0
                gap_mm = 0
                ds = 0 if prev_s is None else (s - prev_s)
                prev_s = s
                _steer(base, (s - MAZE_TARGET_MM) + MAZE_KD_RATIO * ds)
    finally:
        stop()

def left_open():
    return _last_event == "left"

def front_blocked():
    return _last_event == "front"

def nudge(direction="left", degrees=10):
    """Bend the heading a little WHILE STILL DRIVING, then carry straight on
    at the same speed. Motors never stop.

    Angle is an estimate (NUDGE_S_PER_DEG), not a calibrated value - the block
    deliberately does not promise precision. If the robot is not already
    driving, this starts it at the last speed used and leaves it driving.
    """
    try:
        d = float(degrees)
    except (TypeError, ValueError):
        d = 0
    d = min(max(d, 0), 180)
    if d == 0:
        return
    base = _speed(_cur_speed)               # hold whatever speed we are doing
    slow = int(base * NUDGE_SLOW)
    if str(direction).lower() == "left":
        left, right = slow, base
    else:
        left, right = base, slow
    if LEFT_MOTOR == "A":
        da, db = left, right
    else:
        da, db = right, left
    _set_forward(da, db)                    # asymmetric: bend
    time.sleep(d * NUDGE_S_PER_DEG)
    _set_forward(base, base)                # straight again - STILL DRIVING

def _set_forward(duty_a, duty_b):
    """Write forward duties directly - no ramp, no stop. Used by nudge so the
    robot keeps rolling through the correction."""
    a = ("A2", "A1") if FLIP_A else ("A1", "A2")
    b = ("B2", "B1") if FLIP_B else ("B1", "B2")
    _pwm[a[0]].duty(int(duty_a * _trim["A"])); _pwm[a[1]].duty(0)
    _pwm[b[0]].duty(int(duty_b * _trim["B"])); _pwm[b[1]].duty(0)

TURN_TOL_DEG    = 2.0       # close enough
TURN_HOLD_MS    = 100       # must stay inside tolerance this long
TURN_TIMEOUT_MS = 5000


def turn_degrees(direction="left", degrees=90):
    """Spin a chosen angle, measured by the gyro.

    Signature unchanged, so every existing block still works.

    This replaces a scheme that scaled a single timed measurement, whose own
    docstring listed the damage: below about 15 degrees the launch ramp
    dominated and it under-rotated, large angles accumulated error, and
    battery level and floor surface both shifted the result.

    A closed loop on measured angle has none of those. It stops when the
    gyro says it has turned far enough, whatever the battery is doing.
    """
    try:
        d = float(degrees)
    except (TypeError, ValueError):
        return
    d = min(max(d, 0), 450)
    if d == 0:
        return

    if not calibrated():
        print("robot: not characterised - run the motor calibration block")
        return

    import gyro
    # Gyro yaw is positive to the right, so a left turn is a negative target.
    target = -d if str(direction).lower() == "left" else d

    stop()
    _hold_on(target, 0)

    t0 = time.ticks_ms()
    settled = None
    while time.ticks_diff(time.ticks_ms(), t0) < TURN_TIMEOUT_MS:
        err = target - gyro.gyro_turn()
        if abs(err) <= TURN_TOL_DEG:
            if settled is None:
                settled = time.ticks_ms()
            elif time.ticks_diff(time.ticks_ms(), settled) >= TURN_HOLD_MS:
                break
        else:
            settled = None
        time.sleep_ms(10)

    stop()
    return target - gyro.gyro_turn()


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

# Harrison: the sweep values "are likely to be small values like 5-20%".
# There is a hard reason to obey that here: the MPU-6050 defaults to a
# +/-250 deg/s range, and a 110mm robot spinning much above half throttle
# exceeds it. The readings then CLIP, and a straight-line fit through
# clipped data returns a NEGATIVE gain -- which is exactly what a first
# attempt at 250-750 produced. The saturation guard below is the backstop.
SWEEP        = (200, 260, 320, 380, 440, 500)
SPIN_MS      = 900
SETTLE_MS    = 400


def characterise(verbose=True):
    """Measure this robot's Km, Tm and deadband; derive and save the gains.

    Peter Harrison's method (micromouseonline.com, "Characterising the drive
    system on the micromouse"): spin on the spot at several duty levels, let
    each reach a steady angular velocity, and fit a straight line to rate
    against duty. The slope is the DC gain Km. The line does not pass through
    the origin, and that intercept is the drive-system loss -- the deadband,
    for free, with no separate breakaway hunt.

    Tm comes from the 63% point of the step response, since 1-exp(-1)=0.632.

    Spinning on the spot means both wheels roll, so the load is a rolling
    one rather than the scrubbing of dragging a stopped wheel sideways, and
    it needs no room to travel. Run once per robot.
    """
    import gyro
    _hold_off()
    gyro.gyro_setup()
    time.sleep_ms(800)

    pts, tms = [], []
    for duty in SWEEP:
        gyro.gyro_reset()
        last = 0.0
        rates = []
        t0 = time.ticks_ms()
        try:
            _motors_raw(duty, False, duty, True)     # A forward, B reverse
            while time.ticks_diff(time.ticks_ms(), t0) < SPIN_MS:
                time.sleep_ms(LOOP_MS)
                tt = time.ticks_diff(time.ticks_ms(), t0)
                a = gyro.gyro_turn()
                rates.append((tt, abs(a - last) * (1000.0 / LOOP_MS)))
                last = a
        finally:
            stop()
        time.sleep_ms(SETTLE_MS)

        if len(rates) < 6:
            continue
        tail = rates[len(rates) * 2 // 3:]
        ss = sum(r for _, r in tail) / len(tail)
        tm = None
        for tt, r in rates:
            if r >= 0.632 * ss:
                tm = tt / 1000.0
                break
        if verbose:
            print("  duty %4d -> %7.1f deg/s  Tm %s"
                  % (duty, ss, ("%.3f" % tm) if tm else "-"))

        # Past the sensor's range the readings clip and the fit is nonsense.
        # Stop here and use what we have rather than adding bad points.
        if ss >= SAT_LIMIT:
            if verbose:
                print("  (near the gyro's %d deg/s limit - sweep stops here)"
                      % int(GYRO_MAX_DPS))
            if ss > 5.0:
                pts.append((duty, ss))
                if tm:
                    tms.append(tm)
            break

        # A point that did not move tells the fit nothing except that it was
        # under the deadband, and including it drags the line down.
        if ss > 5.0:
            pts.append((duty, ss))
            if tm:
                tms.append(tm)

    if len(pts) < 2 or not tms:
        print("  not enough movement - is the robot on the floor?")
        return None

    n = len(pts)
    sx = sum(p[0] for p in pts); sy = sum(p[1] for p in pts)
    sxy = sum(p[0] * p[1] for p in pts); sxx = sum(p[0] * p[0] for p in pts)
    den = n * sxx - sx * sx
    if den == 0:
        return None
    km = (n * sxy - sx * sy) / den
    if km <= 0:
        # More duty must give more yaw. A negative slope means the data is
        # wrong, not the robot -- almost always gyro clipping.
        print("  fit gave a negative gain - readings are clipping.")
        print("  Lower the SWEEP values and run again.")
        return None
    dead = -((sy - km * sx) / n) / km
    tm = sum(tms) / len(tms)

    # Gains from the measured plant, not guessed. Plant Km/(s(1+Tm.s)) under
    # PD gives s^2 + ((1+Km.Kd)/Tm).s + Km.Kp/Tm = 0; matching that to
    # s^2 + 2.zeta.wn.s + wn^2 with wn = 4/(zeta.tds) gives the two below.
    # These reproduce Harrison's published worked example (Km=142, Tm=0.165
    # -> kP 7.8, kD 0.126) to three figures.
    wn = 4.0 / (ZETA * TDS)
    kp = wn * wn * tm / km
    kd = (2 * ZETA * wn * tm - 1) / km
    if kd < 0:
        kd = 0.0

    global _km, _tm, _dead, _kp, _kd, MAX_DIFF
    _km, _tm, _dead, _kp, _kd = km, tm, dead, kp, kd

    # Cap the correction at the duty that spins us at SAT_LIMIT, so the gyro
    # never clips while the controller is relying on it.
    MAX_DIFF = int(min(dead + SAT_LIMIT / km, 1023))

    try:
        import json
        with open(MMCAL_FILE, "w") as f:
            json.dump({"Km": km, "Tm": tm, "deadband": dead,
                       "kP": kp, "kD": kd}, f)
    except Exception as e:
        print("  could not save:", e)

    print("  Km %.3f  Tm %.3f  deadband %.0f  kP %.2f  kD %.4f"
          % (km, tm, dead, kp, kd))

    # The robot is on the floor and unplugged when this runs, so the console
    # is unreadable. The display is the only output that exists.
    try:
        _oled.fill(0)
        _oled.text("CAL DONE", OLED_X0, OLED_Y0)
        _oled.text("Km %.2f" % km, OLED_X0, OLED_Y0 + 8)
        _oled.text("Tm %.2f" % tm, OLED_X0, OLED_Y0 + 16)
        _oled.text("dz %d" % int(dead), OLED_X0, OLED_Y0 + 24)
        _oled.show()
    except Exception:
        pass

    return (km, tm, dead, kp, kd)


def shutdown():
    """Full teardown, matching the handover's verified order."""
    stop()
    servo_off()
    _timer_stop()                   # no-op when OS_TIMER is False
    _oled.fill(0)
    _oled.show()
