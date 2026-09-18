"""provision_devlink.py - provision the current ESP32-C3 robot system.

This is the working ``provision.py`` flow with only the deployed file set
changed for the compiled robot + Bluetooth DevLink system.

Run from anywhere:
   python C:\\bipes-classroom\\firmware\\provision_devlink.py
   python C:\\bipes-classroom\\firmware\\provision_devlink.py -cal

``-cal`` installs a one-shot autonomous calibration program as ``main.py``.
After provisioning, unplug USB and power the robot from its battery; it starts
calibration after one second.  Add ``--once`` to exit after one board.

Per board: plug it in, press Enter, wait for DONE, unplug, then repeat.
Requires (one-time):  pip install esptool mpremote pyserial
"""

import subprocess
import sys
import time
import os
import argparse


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FIRMWARE_BIN = os.path.join(
    SCRIPT_DIR, "ESP32_GENERIC_C3-20260406-v1.28.0.bin"
)

# (file beside this script, destination filename on the board)
FILES = [
    ("boot.py", "boot.py"),
    ("main.py", "main.py"),
    ("devlink_server.mpy", "devlink_server.mpy"),
    ("ssd1306.py", "ssd1306.py"),
    ("vl53l0x_nb.py", "vl53l0x_nb.py"),
    ("robot.mpy", "robot.mpy"),
    ("gyro.mpy", "gyro.mpy"),
    ("bench.py", "bench.py"),
    ("maze_cal_factory.json", "maze_cal.json"),
    ("robot_commission.py", "devlink_app.py"),
]

# Same runtime, but boot directly into the one-shot autonomous calibration
# image after USB is unplugged and the robot is power-cycled.
CAL_FILES = [
    (("calibration_main.py", "main.py") if board_name == "main.py"
     else (local_name, board_name))
    for local_name, board_name in FILES
]

ESP_VID = "303A"


# Intentionally identical to provision.py.
def find_port():
    from serial.tools import list_ports
    ports = [p.device for p in list_ports.comports()
             if p.vid is not None and ("%04X" % p.vid) == ESP_VID]
    return ports[0] if len(ports) == 1 else (ports, None)[1] if ports else None


# Intentionally identical to provision.py.
def run(cmd, timeout=180):
    print("  >", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise RuntimeError("command failed: " + cmd[0])
    return r.stdout


def provision(port, files=FILES):
    print("[1/4] erasing flash...")
    run([sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", port,
         "erase-flash"])
    print("[2/4] writing MicroPython...")
    run([sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", port,
         "--baud", "921600", "write-flash", "0x0", FIRMWARE_BIN])
    print("      waiting for reboot...")
    time.sleep(4)
    print("[3/4] copying DevLink robot files...")
    for local_name, board_name in files:
        src = os.path.join(SCRIPT_DIR, local_name)
        if not os.path.exists(src):
            raise RuntimeError("missing local file: " + src)
        run([sys.executable, "-m", "mpremote", "connect", port,
             "cp", src, ":" + board_name])
    print("[4/4] verifying (name AND byte size)...")
    out = run([sys.executable, "-m", "mpremote", "connect", port, "fs", "ls"])
    missing = [board_name for _, board_name in files if board_name not in out]
    if missing:
        raise RuntimeError("files missing after copy: %s" % missing)
    board_names = [board_name for _, board_name in files]
    code = ("import os\r"
            "print({f: os.stat(f)[6] for f in %r})" % board_names)
    out = run([sys.executable, "-m", "mpremote", "connect", port, "exec",
               code.replace("\r", "\n")])
    try:
        on_board = eval(out.strip().splitlines()[-1], {"__builtins__": {}}, {})
    except Exception:
        raise RuntimeError("could not read on-board file sizes: " + out.strip())
    bad = []
    for local_name, board_name in files:
        want = os.path.getsize(os.path.join(SCRIPT_DIR, local_name))
        got = on_board.get(board_name, -1)
        flag = "ok" if got == want else "MISMATCH"
        print("      %-20s %6d bytes  %s" % (board_name, got, flag))
        if got != want:
            bad.append("%s: on board %d, expected %d" %
                       (board_name, got, want))
    if bad:
        raise RuntimeError("size mismatch after copy -> " + "; ".join(bad))
    out = run([sys.executable, "-m", "mpremote", "connect", port, "exec",
               "import robot,gyro,devlink_server; "
               "print(robot.VERSION,gyro.VERSION,devlink_server.VERSION); "
               "p={n:c.duty() for n,c in robot._pwm.items()}; print(p); "
               "print('MOTORS_ZERO' if all(v==0 for v in p.values()) "
               "else 'MOTORS_NOT_ZERO')"])
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines or lines[-1] != "MOTORS_ZERO":
        raise RuntimeError("runtime imported but motor outputs were not zero: " + out)
    print("      runtime:", lines[-3])
    print("      motors:", lines[-2])
    return True


def screen_test(port, n):
    print("[5/5] screen test...")
    code = ("import robot, time; robot.show('BOT %d'); time.sleep(1.2); "
            "print('SHOWED')" % n)
    try:
        out = run([sys.executable, "-m", "mpremote", "connect", port,
                   "exec", code], timeout=40)
        if "SHOWED" in out:
            print("      look at the screen: BOT %d" % n)
            return True
    except RuntimeError:
        pass
    print("      WARNING: runtime import/OLED test failed.")
    print("      Files are installed, but check the assembled robot wiring.")
    return False


def reset_to_devlink(port):
    print("      starting Bluetooth DevLink...")
    run([sys.executable, "-m", "mpremote", "connect", port, "reset"],
        timeout=40)
    time.sleep(2)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Provision ESP32-C3 classroom robot firmware")
    parser.add_argument(
        "-cal", "--cal", action="store_true",
        help="install autonomous calibration as main.py; unplug USB and "
             "power-cycle to run it")
    parser.add_argument(
        "--once", action="store_true",
        help="provision one board and exit instead of waiting for the next")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    files = CAL_FILES if args.cal else FILES
    if not os.path.exists(FIRMWARE_BIN):
        sys.exit("firmware bin not found next to this script: %s" % FIRMWARE_BIN)
    absent = [local_name for local_name, _ in files
              if not os.path.exists(os.path.join(SCRIPT_DIR, local_name))]
    if absent:
        sys.exit("missing file(s) in %s: %s" %
                 (SCRIPT_DIR, ", ".join(absent)))
    n = 0
    while True:
        mode = "CALIBRATION" if args.cal else "DEVLINK"
        input("\n=== [%s] plug in the next board, then press Enter "
              "(Ctrl-C to stop) === " % mode)
        port = find_port()
        if port is None:
            print("no (or multiple) Espressif USB device found - "
                  "plug exactly one board")
            continue
        print("board on", port)
        try:
            provision(port, files)
            n += 1
            ok = screen_test(port, n)
            if args.cal:
                print("*** BOARD %d READY TO CALIBRATE%s ***" %
                      (n, "" if ok else " (files only, no screen)"))
                print("    unplug USB, place the robot safely, then power it "
                      "from the battery; calibration starts after 1 second")
            else:
                reset_to_devlink(port)
                print("*** BOARD %d DONE%s - unplug it ***" %
                      (n, "" if ok else " (files only, no screen)"))
        except Exception as e:
            print("!!! FAILED:", e)
            print("    if it failed at step 1/2: unplug, hold BOOT while "
                  "replugging, retry")
        if args.once:
            break


if __name__ == "__main__":
    main()
