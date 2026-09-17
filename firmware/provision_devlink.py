"""Provision the current ESP32-C3 robot + Bluetooth DevLink firmware.

This is deliberately separate from the legacy ``provision.py``.

Typical use (one board):

    python provision_devlink.py --once
    python provision_devlink.py --port COM7

Fleet use (keeps prompting for the next board):

    python provision_devlink.py

One-time PC requirements:

    python -m pip install esptool mpremote pyserial

The large robot, gyro and DevLink modules are installed as precompiled MPY
files.  This avoids compiling them in the ESP32-C3's small heap at boot.  A
safe commissioning program is installed as ``devlink_app.py``; with no input
it only reports status and never commands the servo or motors.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


SCRIPT_DIR = Path(__file__).resolve().parent
FIRMWARE_BIN = SCRIPT_DIR / "ESP32_GENERIC_C3-20260406-v1.28.0.bin"
ESPRESSIF_VID = 0x303A

# (local file, name on the board).  Do not install robot.py, gyro.py or
# devlink_server.py beside their MPY equivalents: source files take heap to
# compile and can mask the tested MPY build.
FILES = (
    ("boot.py", "boot.py"),
    ("main.py", "main.py"),
    ("devlink_server.mpy", "devlink_server.mpy"),
    ("robot.mpy", "robot.mpy"),
    ("gyro.mpy", "gyro.mpy"),
    ("ssd1306.py", "ssd1306.py"),
    ("vl53l0x_nb.py", "vl53l0x_nb.py"),
    ("bench.py", "bench.py"),
    # Generic sensor/geometry data only.  It deliberately excludes another
    # robot's trim, breakaway, plant gains and timed-turn values.
    ("maze_cal_factory.json", "maze_cal.json"),
    ("robot_commission.py", "devlink_app.py"),
)

COMPILED_SOURCES = (
    ("devlink_server.py", "devlink_server.mpy"),
    ("robot.py", "robot.mpy"),
    ("gyro.py", "gyro.mpy"),
)


class ProvisionError(RuntimeError):
    """A board was not completely and verifiably provisioned."""


def run(command: list[str], timeout: float = 180, allow_failure: bool = False):
    print("  >", " ".join(command), flush=True)
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode and not allow_failure:
        if result.stdout:
            print(result.stdout[-3000:])
        if result.stderr:
            print(result.stderr[-3000:])
        raise ProvisionError("command failed: " + command[0])
    return result


def local_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(64 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def local_manifest() -> dict:
    files = {}
    for source_name, target_name in FILES:
        path = SCRIPT_DIR / source_name
        files[target_name] = {
            "source": source_name,
            "size": path.stat().st_size,
            "sha256": local_sha256(path),
        }
    return {
        "schema": 1,
        "system": "esp32-c3-micropython-devlink-robot",
        "firmware": {
            "file": FIRMWARE_BIN.name,
            "size": FIRMWARE_BIN.stat().st_size,
            "sha256": local_sha256(FIRMWARE_BIN),
        },
        "files": files,
    }


def preflight() -> dict:
    missing_modules = [
        package
        for package in ("esptool", "mpremote", "serial")
        if importlib.util.find_spec(package) is None
    ]
    if missing_modules:
        raise ProvisionError(
            "missing PC package(s): %s; run: %s -m pip install esptool "
            "mpremote pyserial"
            % (", ".join(missing_modules), sys.executable)
        )

    required = [FIRMWARE_BIN]
    required.extend(SCRIPT_DIR / source for source, _ in FILES)
    absent = [str(path) for path in required if not path.is_file()]
    if absent:
        raise ProvisionError("missing local file(s): " + ", ".join(absent))

    stale = []
    for source_name, compiled_name in COMPILED_SOURCES:
        source = SCRIPT_DIR / source_name
        compiled = SCRIPT_DIR / compiled_name
        if compiled.stat().st_mtime_ns < source.stat().st_mtime_ns:
            stale.append("%s is older than %s" % (compiled_name, source_name))
    if stale:
        raise ProvisionError(
            "refusing to install stale compiled firmware: " + "; ".join(stale)
        )

    manifest = local_manifest()
    print("Local package checked:")
    print("  MicroPython:", FIRMWARE_BIN.name)
    for target, item in manifest["files"].items():
        print("  %-20s %6d bytes  %s" % (target, item["size"], item["sha256"][:12]))
    return manifest


def esp_ports() -> list[str]:
    from serial.tools import list_ports

    return sorted(
        port.device
        for port in list_ports.comports()
        if port.vid == ESPRESSIF_VID
    )


def other_serial_ports() -> list[str]:
    """Describe non-Espressif ports so a power-only cable is obvious."""
    from serial.tools import list_ports

    return [
        "%s (%s)" % (port.device, port.description)
        for port in list_ports.comports()
        if port.vid != ESPRESSIF_VID
    ]


def legacy_find_port():
    """Call the original provisioner's detector, without running its UI."""
    path = SCRIPT_DIR / "provision.py"
    spec = importlib.util.spec_from_file_location("legacy_robot_provision", path)
    if spec is None or spec.loader is None:
        raise ProvisionError("could not load original provisioner: " + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.find_port()


def select_port(requested: str | None) -> str:
    if requested:
        available = {port.upper(): port for port in esp_ports()}
        if requested.upper() not in available:
            raise ProvisionError(
                "%s is not an attached Espressif USB device (found: %s)"
                % (requested, ", ".join(available.values()) or "none")
            )
        return available[requested.upper()]

    # Use the original provisioner's detector verbatim.  This is kept as a
    # direct call to provision.py so the two installers cannot drift apart.
    legacy_port = legacy_find_port()
    if legacy_port:
        return legacy_port

    ports = esp_ports()
    if not ports:
        others = other_serial_ports()
        detail = "; other serial ports: %s" % ", ".join(others) if others else ""
        raise ProvisionError(
            "the original provisioner also found no Espressif USB device%s"
            % detail
        )
    if len(ports) != 1:
        others = other_serial_ports()
        detail = "; other serial ports: %s" % ", ".join(others) if others else ""
        raise ProvisionError(
            "plug in exactly one Espressif USB device with a data-capable "
            "cable (found: %s%s)"
            % (", ".join(ports) or "none", detail)
        )
    return ports[0]


def mpremote(port: str, *arguments: str, timeout: float = 60):
    command = [
        sys.executable,
        "-m",
        "mpremote",
        "connect",
        port,
        *arguments,
    ]
    return run(command, timeout=timeout)


def wait_for_port(port: str, timeout: float = 20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port.upper() in {item.upper() for item in esp_ports()}:
            return
        time.sleep(0.25)
    raise ProvisionError("board did not return over USB after flashing")


def copy_files(port: str):
    for source_name, target_name in FILES:
        source = SCRIPT_DIR / source_name
        print("      %-20s -> /%s" % (source_name, target_name))
        mpremote(port, "cp", str(source), ":" + target_name)


def board_file_info(port: str) -> dict:
    names = [target for _, target in FILES]
    code = """\
try:
 import hashlib
except ImportError:
 import uhashlib as hashlib
try:
 import binascii
except ImportError:
 import ubinascii as binascii
try:
 import json
except ImportError:
 import ujson as json
import os
names=%r
answer={}
for name in names:
 h=hashlib.sha256()
 size=0
 with open(name,'rb') as source:
  while True:
   block=source.read(512)
   if not block:
    break
   size+=len(block)
   h.update(block)
 answer[name]={'size':size,'sha256':binascii.hexlify(h.digest()).decode()}
print('PROVISION_FILES='+json.dumps(answer))
""" % names
    output = mpremote(port, "exec", code, timeout=90).stdout
    marker = "PROVISION_FILES="
    lines = [line for line in output.splitlines() if line.startswith(marker)]
    if not lines:
        raise ProvisionError("board did not return its file hashes: " + output[-1000:])
    return json.loads(lines[-1][len(marker) :])


def verify_files(port: str, manifest: dict):
    actual = board_file_info(port)
    failures = []
    for target, expected in manifest["files"].items():
        got = actual.get(target, {})
        ok = (
            got.get("size") == expected["size"]
            and got.get("sha256") == expected["sha256"]
        )
        print(
            "      %-20s %6s bytes  %s"
            % (target, got.get("size", "?"), "SHA256 OK" if ok else "MISMATCH")
        )
        if not ok:
            failures.append(target)
    if failures:
        raise ProvisionError(
            "on-board file verification failed: " + ", ".join(failures)
        )


def smoke_test(port: str) -> dict:
    # Importing the runtime may initialize sensors and the OLED, but does not
    # command the servo.  Motor outputs must remain at zero throughout.
    code = """\
try:
 import json
except ImportError:
 import ujson as json
import binascii, machine
import robot, gyro, devlink_server
pwm={name:channel.duty() for name,channel in robot._pwm.items()}
answer={'robot':robot.VERSION,'gyro':gyro.VERSION,
        'devlink':devlink_server.VERSION,'pwm':pwm,
        'uid':binascii.hexlify(machine.unique_id()).decode(),
        'reset_cause':machine.reset_cause()}
print('PROVISION_SMOKE='+json.dumps(answer))
"""
    output = mpremote(port, "exec", code, timeout=60).stdout
    marker = "PROVISION_SMOKE="
    lines = [line for line in output.splitlines() if line.startswith(marker)]
    if not lines:
        raise ProvisionError("runtime smoke test returned no result: " + output[-1000:])
    result = json.loads(lines[-1][len(marker) :])
    if any(int(duty) != 0 for duty in result["pwm"].values()):
        raise ProvisionError("motor PWM was not zero during smoke test: %r" % result["pwm"])
    print(
        "      robot %s, gyro %s, DevLink %s, motors zero"
        % (result["robot"], result["gyro"], result["devlink"])
    )
    return result


def write_board_manifest(port: str, manifest: dict, smoke: dict):
    record = dict(manifest)
    record["board"] = smoke
    record["installed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    encoded = base64.b64encode(body).decode("ascii")
    code = (
        "import binascii\n"
        "body=binascii.a2b_base64(%r)\n"
        "with open('provision_info.json','wb') as f: f.write(body)\n"
        "print('PROVISION_MANIFEST='+str(len(body)))" % encoded
    )
    output = mpremote(port, "exec", code).stdout
    if "PROVISION_MANIFEST=%d" % len(body) not in output:
        raise ProvisionError("could not record provision_info.json")
    print("      provision_info.json recorded (%d bytes)" % len(body))


def reset_into_devlink(port: str):
    # mpremote reset may lose the serial link while the board resets; that is
    # expected.  The previous hash and smoke checks are the completion gate.
    print("[7/7] resetting into Bluetooth DevLink mode...")
    result = run(
        [sys.executable, "-m", "mpremote", "connect", port, "reset"],
        timeout=30,
        allow_failure=True,
    )
    if result.returncode:
        combined = (result.stdout + "\n" + result.stderr).lower()
        if "could not" in combined or "no such" in combined:
            raise ProvisionError("board reset command failed")
    time.sleep(2)


def provision(port: str, manifest: dict):
    print("[1/7] erasing flash...")
    esptool_port = ["--port", port]
    run(
        [
            sys.executable,
            "-m",
            "esptool",
            "--chip",
            "esp32c3",
            *esptool_port,
            "erase-flash",
        ]
    )
    print("[2/7] writing MicroPython...")
    run(
        [
            sys.executable,
            "-m",
            "esptool",
            "--chip",
            "esp32c3",
            *esptool_port,
            "--baud",
            "921600",
            "write-flash",
            "0x0",
            str(FIRMWARE_BIN),
        ]
    )
    print("[3/7] waiting for MicroPython USB...")
    wait_for_port(port)
    time.sleep(2)
    print("[4/7] copying the DevLink robot system...")
    copy_files(port)
    print("[5/7] verifying every installed byte...")
    verify_files(port, manifest)
    print("[6/7] testing imports and safe motor state...")
    smoke = smoke_test(port)
    write_board_manifest(port, manifest, smoke)
    reset_into_devlink(port)
    return smoke


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Provision the compiled ESP32-C3 robot + Bluetooth DevLink system"
    )
    parser.add_argument("--port", help="specific Espressif USB port, for example COM7")
    parser.add_argument(
        "--once", action="store_true", help="provision one detected board and exit"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="validate the local package and dependencies without touching a board",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    try:
        manifest = preflight()
    except ProvisionError as exc:
        raise SystemExit("PRECHECK FAILED: " + str(exc))
    if args.check_only:
        print("CHECK ONLY: package is ready; no board was changed.")
        return 0

    one_board = bool(args.once or args.port)
    number = 0
    while True:
        if not args.port:
            try:
                input(
                    "\n=== Plug in one board, then press Enter "
                    "(Ctrl-C to stop) === "
                )
            except (EOFError, KeyboardInterrupt):
                print("\nStopped.")
                return 0
        try:
            port = select_port(args.port)
            print("Board on", port)
            smoke = provision(port, manifest)
            number += 1
            print(
                "*** BOARD %d DONE: uid=%s, robot=%s, DevLink=%s ***"
                % (number, smoke["uid"], smoke["robot"], smoke["devlink"])
            )
            print("    It is now advertising as MPY-DEV-C3; USB may be unplugged.")
        except ProvisionError as exc:
            print("!!! FAILED:", exc)
            print("    This board did not pass verification and is not marked DONE.")
            if one_board:
                return 1
        if one_board:
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
