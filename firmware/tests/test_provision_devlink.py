"""Host-only checks for the DevLink provisioner file selection."""

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
assert ("robot.mpy", "robot.mpy") in provision.FILES
assert ("gyro.mpy", "gyro.mpy") in provision.FILES
assert ("devlink_server.mpy", "devlink_server.mpy") in provision.FILES
assert ("robot_commission.py", "devlink_app.py") in provision.FILES
assert ("maze_cal_factory.json", "maze_cal.json") in provision.FILES
assert "robot.py" not in targets
assert "gyro.py" not in targets
assert "devlink_server.py" not in targets

cal_targets = [target for _, target in provision.CAL_FILES]
assert cal_targets == targets
assert ("calibration_main.py", "main.py") in provision.CAL_FILES
assert ("main.py", "main.py") not in provision.CAL_FILES
assert provision.parse_args(["-cal"]).cal is True
assert provision.parse_args(["--cal"]).cal is True
assert provision.parse_args(["--once"]).once is True

with open(os.path.join(FIRMWARE, "calibration_main.py"), encoding="utf-8") as source:
    calibration_main = source.read()
assert "robot.characterise(restart=True)" in calibration_main
assert "if not robot._gyro_present:" in calibration_main
assert "CAL NOT RUN: no gyro" in calibration_main

with open(os.path.join(FIRMWARE, "maze_cal_factory.json"), encoding="utf-8") as source:
    factory = json.load(source)
for key in ("trim", "breakaway_A", "breakaway_B", "t90_left", "t90_right"):
    assert key not in factory

legacy_path = os.path.join(FIRMWARE, "provision.py")
legacy_spec = importlib.util.spec_from_file_location("legacy_provision", legacy_path)
legacy = importlib.util.module_from_spec(legacy_spec)
legacy_spec.loader.exec_module(legacy)
assert provision.find_port.__code__.co_code == legacy.find_port.__code__.co_code
new_nested = [value.co_code for value in provision.find_port.__code__.co_consts
              if hasattr(value, "co_code")]
old_nested = [value.co_code for value in legacy.find_port.__code__.co_consts
              if hasattr(value, "co_code")]
assert new_nested == old_nested

with open(PATH, encoding="utf-8") as source:
    provision_source = source.read()
assert "all(v==0 for v in p.values())" in provision_source
assert "lines[-1] != \"MOTORS_ZERO\"" in provision_source

print("provision_devlink tests passed")
