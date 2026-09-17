"""Static safety checks for BIPES robot block generators."""

from pathlib import Path


root = Path(__file__).resolve().parents[2]
source = (root / "ui" / "core" / "queue.js").read_text(encoding="utf-8")
start = source.index("Blockly.Blocks['mmcal']")
end = source.index("/* Calibrate motors", start)
compatibility_block = source[start:end]

assert "FieldNumber(300, 0, 300" in compatibility_block
assert "Blockly.Python.definitions_['mmcal_src']" not in compatibility_block
assert "robot.characterise()" in compatibility_block
assert "robot.turn_degrees" in compatibility_block
assert "robot.forward_at(" in compatibility_block
assert "Math.min(300" in compatibility_block
assert "FieldNumber(2, 0.5, 8" in compatibility_block
assert "Math.min(8" in compatibility_block
assert "robot.stop()" in compatibility_block

exact_start = source.index("Blockly.Blocks['robot_forward_at']")
exact_end = source.index("/* ---- DevLink data", exact_start)
exact_block = source[exact_start:exact_end]
assert "FieldNumber(300, 0, 300" in exact_block
assert "backward_at" in exact_block

gyro_start = source.index("Blockly.Blocks['gyro_calibrate']")
gyro_end = source.index("var MMCAL_SRC", gyro_start)
gyro_block = source[gyro_start:gyro_end]
assert "FieldNumber(300, 0, 300" in gyro_block
assert "Blockly.Python.definitions_['gyrocal_src']" not in gyro_block
assert "robot.characterise()" in gyro_block
assert "robot.forward_at(" in gyro_block
assert "Math.min(300" in gyro_block
assert "FieldNumber(2, 0.5, 8" in gyro_block
assert "Math.min(8" in gyro_block
assert "'yaw_deg'" in gyro_block
assert "robot.stop()" in gyro_block

cal_start = source.index("Blockly.Python['robot_calibrate']")
cal_end = source.index("});", cal_start)
cal_generator = source[cal_start:cal_end]
assert "_devlink_result" in cal_generator

print("ALL PASS")
