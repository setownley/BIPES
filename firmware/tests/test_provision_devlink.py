"""Host-only checks for the new compiled DevLink provisioner."""

import importlib.util
import json
import os


HERE = os.path.dirname(os.path.abspath(__file__))
FIRMWARE = os.path.dirname(HERE)
PATH = os.path.join(FIRMWARE, "provision_devlink.py")

spec = importlib.util.spec_from_file_location("provision_devlink", PATH)
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


targets = [target for _, target in provision.FILES]
assert len(targets) == len(set(targets))
assert "robot.mpy" in targets
assert "gyro.mpy" in targets
assert "devlink_server.mpy" in targets
assert "robot.py" not in targets
assert "gyro.py" not in targets
assert "devlink_server.py" not in targets
assert ("robot_commission.py", "devlink_app.py") in provision.FILES
assert ("maze_cal_factory.json", "maze_cal.json") in provision.FILES

with open(os.path.join(FIRMWARE, "maze_cal_factory.json"), encoding="utf-8") as source:
    factory_cal = json.load(source)
for robot_specific_key in (
    "trim",
    "breakaway_duty",
    "breakaway_A",
    "breakaway_B",
    "t90_left",
    "t90_right",
    "speed_slow",
    "speed_medium",
    "speed_fast",
):
    assert robot_specific_key not in factory_cal

manifest = provision.local_manifest()
assert manifest["schema"] == 1
assert manifest["system"] == "esp32-c3-micropython-devlink-robot"
assert set(manifest["files"]) == set(targets)
for target, item in manifest["files"].items():
    source = os.path.join(FIRMWARE, item["source"])
    assert item["size"] == os.path.getsize(source)
    assert len(item["sha256"]) == 64
    int(item["sha256"], 16)

args = provision.parse_args(["--port", "COM9", "--once"])
assert args.port == "COM9" and args.once and not args.check_only


# Exact hash equality is the completion gate, not a filename-only check.
original_info = provision.board_file_info
try:
    provision.board_file_info = lambda _port: {
        name: {"size": item["size"], "sha256": item["sha256"]}
        for name, item in manifest["files"].items()
    }
    provision.verify_files("COM_TEST", manifest)

    broken = provision.board_file_info("COM_TEST")
    broken[targets[0]] = dict(broken[targets[0]], sha256="0" * 64)
    provision.board_file_info = lambda _port: broken
    try:
        provision.verify_files("COM_TEST", manifest)
        raise AssertionError("a bad on-board hash was accepted")
    except provision.ProvisionError as exc:
        assert targets[0] in str(exc)
finally:
    provision.board_file_info = original_info


# Smoke-test parsing must reject any non-zero motor channel.
class Result:
    def __init__(self, stdout):
        self.stdout = stdout


original_mpremote = provision.mpremote
try:
    good = {
        "robot": "1.2.59",
        "gyro": "1.2.2",
        "devlink": "1.3.7",
        "pwm": {"A1": 0, "A2": 0, "B1": 0, "B2": 0},
        "uid": "01020304",
        "reset_cause": 2,
    }
    provision.mpremote = lambda *_args, **_kwargs: Result(
        "boot text\nPROVISION_SMOKE=" + json.dumps(good) + "\n"
    )
    assert provision.smoke_test("COM_TEST")["pwm"]["A1"] == 0

    bad = dict(good, pwm=dict(good["pwm"], B2=1))
    provision.mpremote = lambda *_args, **_kwargs: Result(
        "PROVISION_SMOKE=" + json.dumps(bad) + "\n"
    )
    try:
        provision.smoke_test("COM_TEST")
        raise AssertionError("non-zero motor PWM was accepted")
    except provision.ProvisionError as exc:
        assert "PWM was not zero" in str(exc)
finally:
    provision.mpremote = original_mpremote


print("provision_devlink tests passed")
