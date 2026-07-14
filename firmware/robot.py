# robot.py — classroom runtime for ESP32-C3 Super Mini robot (01Space OLED variant)
# Deploy to the board's flash root:  mpremote cp robot.py :
# Every BIPES custom block compiles to a one-line call into this module.
#
# HARD RULE FOR THIS FILE: this module is the ONLY code that ever touches
# Timer 0, the sensors, or the OLED. Student-generated code must only call
# the public functions at the bottom.

VERSION = "0.5.4"  # must match the block set deployed in the BIPES fork

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
RAMP_MS = 200               # soft-start: motor duty ramps to target over this
RAMP_STEPS = 10             # ... in this many steps (stop() is always instant)
BRAKE_MS = 300              # stop(): active brake (both inputs high) before coast
LAUNCH_HOLD_MS = 100        # standstill launch: hold at breakaway before ramping
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
MAZE_ADVANCE_MM = 230       # parks the PIVOT at gap center: 120 (sensor->axle) + 150 (half gap) - ~40 (debounce travel)
MAZE_GAP_MM = 450           # 1.5 cells with no wall = treat as open
MAZE_SPEED = "slow"         # 290 mm/s: 29 mm/tick staleness
NUDGE_SLOW = 0.55           # nudged wheel runs at this fraction of the other
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
    global _dist_mm, _side_mm, _qre_raw, _tick
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

_tim = Timer(0)             # Timer IDs 0-1 only on the C3; 1 is kept free
_tim.init(period=TICK_MS, mode=Timer.PERIODIC, callback=_tick_cb)

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
def forward(speed="medium"):
    _motors(_speed(speed), False, _speed(speed), False)

def backward(speed="medium"):
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

def nudge(direction="left", seconds=0.3):
    """Creep forward with one wheel slowed - a small steering correction.
    'left' curves left (left wheel slowed). Uses medium speed."""
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        s = 0
    s = min(max(s, 0), 5)                   # clamp 0-5 s
    if s == 0:
        return
    base = _speed("medium")
    slow = int(base * NUDGE_SLOW)
    if str(direction).lower() == "left":
        left, right = slow, base
    else:
        left, right = base, slow
    if LEFT_MOTOR == "A":
        da, db = left, right
    else:
        da, db = right, left
    _motors(da, False, db, False)           # ramped launch, trim applied
    time.sleep(s)
    stop()

def turn_degrees(direction="left", degrees=90):
    """Spin a chosen angle by scaling this robot's calibrated t90.

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
    time.sleep(t)
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

def shutdown():
    """Full teardown, matching the handover's verified order."""
    stop()
    _tim.deinit()
    _oled.fill(0)
    _oled.show()
