"""provision.py - fleet provisioning for ESP32-C3 SuperMini classroom robots.

Lives in the firmware folder next to the .bin and robot files. Run from anywhere:\n   python C:\\bipes-classroom\\firmware\\provision.py
Per board: plug it in, press Enter, wait for DONE (~60s), unplug, next.

Requires (one-time):  pip install esptool mpremote pyserial
Uses:  firmware\\ESP32_GENERIC_C3-20260406-v1.28.0.bin  + the 5 robot files.
"""

import subprocess
import sys
import time
import glob
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # = the firmware folder
FIRMWARE_BIN = os.path.join(SCRIPT_DIR, "ESP32_GENERIC_C3-20260406-v1.28.0.bin")
FILES = ["boot.py", "ssd1306.py", "vl53l0x_nb.py", "robot.py", "bench.py",
         "maze_cal.json"]   # maze_cal = robot #1's values as a TEMPLATE:
                            # per-robot trim/launch/turn cals overwrite it later.
ESP_VID = "303A"            # Espressif native USB


def find_port():
    from serial.tools import list_ports
    ports = [p.device for p in list_ports.comports()
             if p.vid is not None and ("%04X" % p.vid) == ESP_VID]
    return ports[0] if len(ports) == 1 else (ports, None)[1] if ports else None


def run(cmd, timeout=180):
    print("  >", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise RuntimeError("command failed: " + cmd[0])
    return r.stdout


def provision(port):
    print("[1/4] erasing flash...")
    run([sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", port,
         "erase-flash"])
    print("[2/4] writing MicroPython...")
    run([sys.executable, "-m", "esptool", "--chip", "esp32c3", "--port", port,
         "--baud", "921600", "write-flash", "0x0", FIRMWARE_BIN])
    print("      waiting for reboot...")
    time.sleep(4)
    print("[3/4] copying robot files...")
    for f in FILES:
        src = os.path.join(SCRIPT_DIR, f)
        if not os.path.exists(src):
            raise RuntimeError("missing local file: " + src)
        run([sys.executable, "-m", "mpremote", "connect", port, "cp", src, ":" + f])
    print("[4/4] verifying...")
    out = run([sys.executable, "-m", "mpremote", "connect", port, "fs", "ls"])
    missing = [f for f in FILES if f not in out]
    if missing:
        raise RuntimeError("files missing after copy: %s" % missing)
    ver = run([sys.executable, "-m", "mpremote", "connect", port, "exec",
               "print(open('robot.py').readline() + open('robot.py').readlines()[8])"])
    print("      on-board robot.py header:", ver.strip().splitlines()[-1])
    return True


def screen_test(port, n):
    """[5/5] import robot on the board (full peripheral init = smoke test)
    and put the board number on the OLED. Bare board (no OLED) = warning."""
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
    print("      WARNING: robot.py import failed on this board - files are")
    print("      installed, but OLED/I2C init did not run (bare board, or")
    print("      wiring issue if this is an assembled robot).")
    return False


def main():
    if not os.path.exists(FIRMWARE_BIN):
        sys.exit("firmware bin not found next to this script: %s" % FIRMWARE_BIN)
    n = 0
    while True:
        input("\n=== plug in the next board, then press Enter (Ctrl-C to stop) === ")
        port = find_port()
        if port is None:
            print("no (or multiple) Espressif USB device found - plug exactly one board")
            continue
        print("board on", port)
        try:
            provision(port)
            n += 1
            ok = screen_test(port, n)
            print("*** BOARD %d DONE%s - unplug it ***" % (n, "" if ok else " (files only, no screen)"))
        except Exception as e:
            print("!!! FAILED:", e)
            print("    if it failed at step 1/2: unplug, hold BOOT while replugging, retry")


if __name__ == "__main__":
    main()
