# mmcal.py - drive characterisation and heading control, Harrison method.
#
#   import mmcal
#   mmcal.characterise()     # measure Km, Tm and the deadband
#   mmcal.turn(90)           # PD position control on heading
#   mmcal.forward(700, 2.0)  # drive, holding heading with the same controller
#
# Method from Peter Harrison, micromouseonline.com:
#   "Characterising the drive system on the micromouse" (2011-05-15)
#   "Designing the motor controller" (2011-05-15)
#
# WHY ROTATION AND NOT PER-WHEEL
#   Harrison characterises the ROTATION system, spinning the mouse on the spot
#   with one motor forward and one back: "it is easy to do without finding a
#   long stretch of maze. The mouse only has to spin on the spot."
#
#   That matters here for three reasons. Both wheels roll, so the load is a
#   rolling load rather than the scrubbing of dragging a stopped wheel
#   sideways. It needs no floor space. And the thing it measures -- how the
#   robot's yaw responds to a duty DIFFERENCE -- is exactly what both a
#   steering controller and a turn controller command.
#
#   So one characterisation serves both. Holding a straight line is position
#   control on heading with a target of zero; a 90 degree turn is the same
#   controller with a target of 90.
#
# WHAT COMES OUT
#   Km        yaw rate per unit of duty difference, deg/s per count
#   Tm        motor time constant, seconds
#   deadband  the duty difference below which nothing moves. Harrison:
#             "the line does not go through the origin. This is because of
#             losses in the drive system." It falls out of the straight-line
#             fit for free -- no separate breakaway hunt needed.
#
# GAINS
#   Derived from Km and Tm rather than guessed, per Harrison's second post.
#   The formulas below reproduce his published worked example (Km=142,
#   Tm=0.165, zeta=0.7, tds=0.070 -> kP=7.8, kD=0.126) to three figures,
#   which is the check that they are the right formulas.
#
# ONE DEPARTURE FROM HARRISON
#   He samples at 1ms and settles in 70ms. Our gyro sampler runs at 20ms, so
#   70ms is four samples and the discrete loop would be unstable. TDS below
#   is 0.25s, giving about twelve samples per settle. Still a quick turn.

import time

import robot
import gyro

CAL_FILE = "mmcal.json"

# --- characterisation sweep ------------------------------------------------
# Harrison: "They are likely to be small values like 5-20%." On a 1023 scale
# that is 50-200, but an N20 on carpet needs more to move at all, so the
# sweep starts higher and the fit discards points that did not move.
SWEEP = (250, 350, 450, 550, 650, 750)
SPIN_MS = 900          # long enough to reach steady state: several x Tm
SAMPLE_MS = 20         # matches the gyro sampler; no point going faster
SETTLE_MS = 400        # let it stop between runs

# --- controller design -----------------------------------------------------
ZETA = 0.7             # Harrison: "a slightly underdamped system with an
                       # overshoot of a couple of percent"
TDS = 0.25             # settling time. See note above about 20ms sampling.
LOOP_MS = 20

MAX_DIFF = 400         # cap on the duty difference the controller may ask for


def _spin(duty, ms):
    """Spin on the spot at a fixed duty difference. Returns [(t_ms, deg/s)].

    One motor forward, one back, exactly as Harrison describes. Any other
    control must be off -- he is explicit that the mouse is "allowed to
    accelerate up to a constant angular velocity" with nothing interfering.
    """
    out = []
    gyro.gyro_reset()
    last_deg = 0.0
    t0 = time.ticks_ms()
    try:
        robot._motors(duty, False, duty, True)      # A fwd, B reverse
        while True:
            t = time.ticks_diff(time.ticks_ms(), t0)
            if t >= ms:
                break
            time.sleep_ms(SAMPLE_MS)
            t = time.ticks_diff(time.ticks_ms(), t0)
            deg = gyro.gyro_turn()
            if out:
                dt = (t - out[-1][0]) / 1000.0
                if dt > 0:
                    out.append((t, (deg - last_deg) / dt))
            else:
                out.append((t, 0.0))
            last_deg = deg
    finally:
        robot.stop()
    time.sleep_ms(SETTLE_MS)
    return out


def _steady(trace):
    """Steady-state rate: mean of the last third of the run.

    Harrison: "Record that value by averaging over some suitable period -
    say 1 second or so".
    """
    if len(trace) < 6:
        return 0.0
    tail = trace[len(trace) * 2 // 3:]
    return sum(abs(r) for _, r in tail) / len(tail)


def _time_constant(trace, steady):
    """Tm from the 63% point.

    Harrison: "finding the time where each graph passes through an angular
    velocity that is 63% of the steady state value. This is because
    1-exp(-1) = 0.632."
    """
    if steady <= 0:
        return None
    target = 0.632 * steady
    for t, r in trace:
        if abs(r) >= target:
            return t / 1000.0
    return None


def _fit(points):
    """Least squares y = m.x + c over (duty, rate). Returns (Km, deadband)."""
    n = len(points)
    if n < 2:
        return (None, None)
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    den = n * sxx - sx * sx
    if den == 0:
        return (None, None)
    m = (n * sxy - sx * sy) / den
    c = (sy - m * sx) / n
    dead = -c / m if m else None      # x-intercept: the drive-system losses
    return (m, dead)


def gains(km, tm, zeta=ZETA, tds=TDS):
    """PD gains from the measured plant.

    Plant Km/(s(1+Tm.s)) under PD gives
        s^2 + ((1+Km.Kd)/Tm).s + Km.Kp/Tm = 0
    Matching s^2 + 2.zeta.wn.s + wn^2, with wn from the 2% settling time:
        Kp = wn^2.Tm/Km
        Kd = (2.zeta.wn.Tm - 1)/Km
    """
    wn = 4.0 / (zeta * tds)
    kp = wn * wn * tm / km
    kd = (2 * zeta * wn * tm - 1) / km
    return (kp, kd if kd > 0 else 0.0)


def characterise(save=True, verbose=True):
    """Measure Km, Tm and the deadband. The robot spins on the spot.

    Needs only its own footprint of floor -- no straight run.
    """
    print("")
    print("== DRIVE CHARACTERISATION (Harrison method) ==")
    print("The robot spins on the spot. It needs no room to travel.")
    print("")
    gyro.gyro_setup()
    print("gyro calibrating - keep the robot still")
    time.sleep_ms(800)

    pts = []
    tms = []
    for duty in SWEEP:
        tr = _spin(duty, SPIN_MS)
        ss = _steady(tr)
        tm = _time_constant(tr, ss)
        if verbose:
            print("  duty %4d -> %7.1f deg/s   Tm %s"
                  % (duty, ss, ("%.3f s" % tm) if tm else "-"))
        # A point where nothing turned tells the fit nothing except that it
        # was below the deadband, and including it drags the line down.
        if ss > 5.0:
            pts.append((duty, ss))
            if tm:
                tms.append(tm)

    if len(pts) < 2:
        print("  not enough points moved - is the robot on the floor?")
        return None

    km, dead = _fit(pts)
    tm = sum(tms) / len(tms) if tms else None
    if km is None or tm is None:
        print("  fit failed")
        return None

    kp, kd = gains(km, tm)

    print("")
    print("  Km       %.3f deg/s per duty count" % km)
    print("  Tm       %.3f s" % tm)
    print("  deadband %.0f duty  (drive-system losses)" % dead)
    print("  kP       %.3f" % kp)
    print("  kD       %.4f" % kd)
    print("")
    print("  settling %.2f s, zeta %.1f" % (TDS, ZETA))

    cal = {"Km": km, "Tm": tm, "deadband": dead, "kP": kp, "kD": kd}
    if save:
        try:
            import json
            with open(CAL_FILE, "w") as f:
                json.dump(cal, f)
            print("  saved to %s" % CAL_FILE)
        except Exception as e:
            print("  could not save:", e)
    return cal


def _load():
    try:
        import json
        with open(CAL_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------------
# The controller. One PD loop, used for both turning and holding a line.
# ---------------------------------------------------------------------------

def _pd(target_deg, base_duty, timeout_ms, tol_deg, hold_ms, cal):
    """PD position control on heading.

    Harrison's parallel form, verbatim in structure:

        errorOld = error;
        error = setPos - currentPos;
        PWM   = kP * error;
        PWM  += kD * (error - errorOld);

    base_duty 0 means spin on the spot; anything else drives forward at that
    duty while the controller steers.
    """
    kp, kd = cal["kP"], cal["kD"]
    dead = cal["deadband"]

    err_old = target_deg - gyro.gyro_turn()
    t0 = time.ticks_ms()
    in_tol_since = None

    try:
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            err = target_deg - gyro.gyro_turn()

            diff = kp * err + kd * (err - err_old) * (1000.0 / LOOP_MS)
            err_old = err

            # Below the deadband nothing happens at all, so a small demand
            # would simply be ignored. Lift it over the threshold instead --
            # this is what the intercept from the fit is for.
            if diff > 1:
                diff += dead
            elif diff < -1:
                diff -= dead

            if diff > MAX_DIFF:
                diff = MAX_DIFF
            elif diff < -MAX_DIFF:
                diff = -MAX_DIFF

            if base_duty == 0:
                # Spinning on the spot: SAME magnitude both wheels, opposite
                # directions. Computing da = +diff and db = -diff and then
                # taking the sign of each separately does not work -- db
                # comes out negative, its reverse flag reads False, and both
                # wheels drive forward. The robot then drives away in a
                # straight line instead of turning, which is exactly what it
                # did the first time this was tested.
                mag = int(min(abs(diff), 1023))
                robot._motors(mag, diff < 0, mag, diff > 0)
            else:
                da = base_duty + diff
                db = base_duty - diff
                robot._motors(int(min(max(da, 0), 1023)), False,
                              int(min(max(db, 0), 1023)), False)

            if abs(err) <= tol_deg:
                if in_tol_since is None:
                    in_tol_since = time.ticks_ms()
                elif time.ticks_diff(time.ticks_ms(), in_tol_since) >= hold_ms:
                    return err
            else:
                in_tol_since = None

            time.sleep_ms(LOOP_MS)
    finally:
        if base_duty == 0:
            robot.stop()
    return target_deg - gyro.gyro_turn()


def turn(degrees, tol=2.0):
    """Turn on the spot. + is right, - is left."""
    cal = _load()
    if cal is None:
        print("mmcal: run characterise() first")
        return None
    gyro.gyro_setup()
    time.sleep_ms(600)
    gyro.gyro_reset()
    err = _pd(degrees, 0, 4000, tol, 100, cal)
    robot.stop()
    print("turn %+.0f -> off by %+.1f deg" % (degrees, err))
    return err


def forward(duty, seconds, tol=1.0):
    """Drive forward holding the heading it started on.

    Same controller as turn(), target zero. That is the point of
    characterising rotation: steering and turning are the same problem.
    """
    cal = _load()
    if cal is None:
        print("mmcal: run characterise() first")
        return None
    gyro.gyro_setup()
    time.sleep_ms(600)
    gyro.gyro_reset()
    err = _pd(0.0, duty, int(seconds * 1000), tol, 10 ** 9, cal)
    robot.stop()
    print("drove %.1fs -> off by %+.1f deg" % (seconds, err))
    return err
