# bench.py — Phase-1 maze characterization for robot.py v0.2.0
# Copy to the board (BIPES Files tab, filename: bench.py), then at the REPL:
#   import bench
#   bench.run()          # full guided session, ~30-45 min
#   bench.run("side")    # or one section: side/speed/turn/geometry
# Results are printed AND saved to maze_cal.json on flash for robot.py v0.3.0.
#
# Every motor action is wrapped in try/finally robot.stop().

import robot
import time
import json

CAL_FILE = "maze_cal.json"

# Start from whatever is already on flash so partial runs MERGE, never wipe.
try:
    with open(CAL_FILE) as _f:
        RESULTS = json.load(_f)
except (OSError, ValueError):
    RESULTS = {}


def _ask_num(prompt):
    while True:
        s = input(prompt + " > ")
        try:
            return float(s)
        except ValueError:
            print("  enter a number, e.g. 137 or 88.5")


def _pause(msg):
    input(msg + "  [Enter when ready]")


# ---------------------------------------------------------------- side sensor
def side():
    print("")
    print("== SIDE SENSOR ERROR CURVE ==")
    print("Flat wall target (cardboard box). Ruler from SENSOR FACE to wall.")
    curve = []
    for true_mm in (50, 100, 150, 200, 300, 500):
        _pause("Place wall at exactly %d mm from the sensor face" % true_mm)
        vals = []
        bad = 0
        for _ in range(20):
            v = robot.side_mm()
            if v == 9999:
                bad += 1
            else:
                vals.append(v)
            time.sleep_ms(120)   # > one 100 ms tick -> mostly fresh samples
        if vals:
            mean = sum(vals) // len(vals)
            print("  true %4d: mean %4d  min %4d  max %4d  err %+4d  (9999s: %d/20)"
                  % (true_mm, mean, min(vals), max(vals), mean - true_mm, bad))
            curve.append([true_mm, mean, min(vals), max(vals), bad])
        else:
            print("  true %4d: NO VALID READINGS (20/20 were 9999)" % true_mm)
            curve.append([true_mm, None, None, None, bad])
    RESULTS["side_curve"] = curve
    errs = [c[1] - c[0] for c in curve if c[1] is not None]
    if errs:
        print("errors:", errs)
        print("If these are roughly constant -> offset fix = %+d mm" %
              (sum(errs) // len(errs)))
        RESULTS["side_offset_mean"] = sum(errs) // len(errs)
    _save()


# --------------------------------------------------------------- speed/coast
def speed():
    print("")
    print("== SPEED + COAST-DOWN (6 floor runs) ==")
    print("Each run: robot starts at a tape mark, drives, stops, coasts.")
    print("Measure TOTAL distance travelled (mark to final resting spot), in mm.")
    for name in ("slow", "medium", "fast"):
        d = {}
        for secs in (1, 2):
            _pause("Run: %s for %ds. Place robot on the mark" % (name, secs))
            try:
                robot.forward(name)
                robot.wait(secs)
            finally:
                robot.stop()
            d[secs] = _ask_num("  total distance travelled (mm)")
        v = d[2] - d[1]              # mm/s  (coast cancels: d2-d1 = v*1s)
        c = d[1] - v                 # coast mm (d1 = v*1 + coast)
        print("  %s: speed = %d mm/s, coast = %d mm  [v=d2-d1, coast=d1-v]"
              % (name, v, c))
        RESULTS["speed_" + name] = {"mm_s": v, "coast_mm": c,
                                    "d1": d[1], "d2": d[2]}
    _save()


# --------------------------------------------------------------------- turns
def turn():
    print("")
    print("== 90-DEGREE TURN TIME ==")
    print("Tape a 90-degree corner on the floor. Align robot on one leg.")
    for direction in ("left", "right"):
        t = 0.5
        while True:
            _pause("Turn %s for %.2fs. Align robot on the mark" % (direction, t))
            try:
                robot.turn(direction)
                robot.wait(t)
            finally:
                robot.stop()
            a = _ask_num("  angle actually turned (degrees, estimate vs tape)")
            if a <= 0:
                print("  need a positive angle; repeating same t")
                continue
            t_new = t * 90.0 / a
            print("  -> implies t90 = %.2fs" % t_new)
            if abs(a - 90) <= 5:
                ok = input("  within 5 deg. Accept %.2fs? (y/n) > " % t)
                if ok.strip().lower().startswith("y"):
                    RESULTS["t90_" + direction] = t
                    break
            t = t_new
    print("NOTE: repeat this section once on a LOW battery to see the drift band.")
    _save()


# ------------------------------------------------------------------ geometry
def geometry():
    print("")
    print("== GEOMETRY (ruler, robot powered off is fine) ==")
    g = {}
    g["sensor_to_rear_axle_mm"] = _ask_num(
        "side-sensor face to REAR axle line, along robot length (mm)")
    g["length_mm"] = _ask_num("robot overall length incl. wires (mm)")
    g["width_mm"] = _ask_num("robot overall width (mm)")
    g["diag_mm"] = int((g["length_mm"] ** 2 + g["width_mm"] ** 2) ** 0.5)
    print("  spin-turn swept diagonal = %d mm (corridor must exceed this + margin)"
          % g["diag_mm"])
    g["side_sensor_height_mm"] = _ask_num("side-sensor centre height above floor (mm)")
    RESULTS["geometry"] = g
    _save()





# ------------------------------------------------------- launch yaw tuning
def launchtune():
    print("")
    print("== LAUNCH YAW TUNE ==")
    print("Robot launches at fast from standstill each pass (1.2s).")
    print("Judge the LAUNCH yaw only - the first half second.")
    a, b = robot.get_breakaway()
    print("starting floors: A=%d B=%d" % (a, b))
    while True:
        _pause("Place robot on the line, pointing at a distant mark")
        try:
            robot.forward("fast")
            robot.wait(1.2)
        finally:
            robot.stop()
        ans = input("  launch yawed (l)eft, (r)ight, or (s)traight? > ").strip().lower()
        if ans.startswith("s"):
            RESULTS["breakaway_A"] = a
            RESULTS["breakaway_B"] = b
            _save()
            print("  floors locked: A=%d B=%d" % (a, b))
            break
        elif ans.startswith("l"):
            a, b = robot.set_breakaway(a + 10, b - 10)   # strengthen left launch
        elif ans.startswith("r"):
            a, b = robot.set_breakaway(a - 10, b + 10)   # strengthen right launch
        else:
            print("  l, r or s")
            continue
        print("  floors now A=%d B=%d" % (a, b))

# ------------------------------------------------------------- launch floor
def launch():
    print("")
    print("== LAUNCH (PER-WHEEL BREAKAWAY) ==")
    print("Prop the robot up so BOTH wheels spin freely in the air.")
    for ch, label in (("A", "channel A wheel"), ("B", "channel B wheel")):
        found = None
        for d in range(150, 650, 50):
            _pause("Test %s at duty %d" % (label, d))
            try:
                if ch == "A":
                    robot._drive_one("A", d)
                else:
                    robot._drive_one("B", d)
                robot.wait(0.7)
            finally:
                robot.stop()
            ans = input("  did the %s spin? (y/n) > " % label).strip().lower()
            if ans.startswith("y"):
                found = d
                break
        if found is None:
            print("  no spin up to 600 - check motor; nothing saved for %s" % ch)
            return
        RESULTS["breakaway_" + ch] = found
        print("  breakaway_%s = %d" % (ch, found))
    _save()
    print("Saved. Re-import robot to activate.")

# ----------------------------------------------------------------- veer trim
def trim():
    print("")
    print("== STRAIGHT-DRIVE TRIM ==")
    print("Robot drives forward (medium, 1.5s) each pass on open floor.")
    print("Answer which way it veered; trim adjusts 2 percent per pass.")
    right_ch_is_b = (robot.LEFT_MOTOR == "A")
    while True:
        _pause("Place robot on open floor, pointing at a distant mark")
        try:
            robot.forward("medium")
            robot.wait(1.5)
        finally:
            robot.stop()
        ans = input("  veered (l)eft, (r)ight, or (s)traight? > ").strip().lower()
        a, b = robot.get_trim()
        if ans.startswith("s"):
            robot.save_trim()
            RESULTS["trim"] = {"A": a, "B": b}
            print("  trim locked: A=%.2f B=%.2f" % (a, b))
            break
        elif ans.startswith("l"):
            # veering left = right motor stronger -> scale right side down
            if right_ch_is_b:
                robot.set_trim(b=b * 0.98)
            else:
                robot.set_trim(a=a * 0.98)
        elif ans.startswith("r"):
            if right_ch_is_b:
                robot.set_trim(a=a * 0.98)
            else:
                robot.set_trim(b=b * 0.98)
        else:
            print("  l, r or s")
        print("  trim now A=%.2f B=%.2f" % robot.get_trim())
    _save()

# -------------------------------------------------------------------- runner
def _save():
    try:
        with open(CAL_FILE, "w") as f:
            json.dump(RESULTS, f)
        print("[saved -> %s]" % CAL_FILE)
    except OSError as e:
        print("[WARN: could not save:", e, "]")


def run(only=None):
    steps = {"launchtune": launchtune, "launch": launch, "trim": trim, "side": side, "speed": speed, "turn": turn, "geometry": geometry}
    if only:
        steps[only]()
    else:
        for k in ("launch", "trim", "side", "speed", "turn", "geometry"):
            steps[k]()
    print("")
    print("==== RESULTS ====")
    print(json.dumps(RESULTS))
    print("Saved to %s — robot.py v0.3.0 will read this file." % CAL_FILE)
