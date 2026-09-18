"""One-shot cable-free calibration program installed by ``-cal``.

The provisioner writes this file to the board as ``main.py``.  Provisioning
does not reset into it: unplug USB, place the robot safely, then power it from
its battery.  Calibration begins after one second.
"""

import os
import time
import robot

robot.apply_settings()

# Rename first so a successful calibration cannot accidentally run again on
# the next boot.  A failure keeps calibration_attempt.py for diagnosis, while
# saving an ordinary BIPES program later simply installs a new main.py.
try:
    os.remove("calibration_attempt.py")
except OSError:
    pass
try:
    os.rename("main.py", "calibration_attempt.py")
except OSError:
    pass

time.sleep(1)

if not robot._gyro_present:
    robot._timer_stop()
    try:
        with open("cal_log.txt", "w") as log:
            log.write("CAL NOT RUN: no gyro at I2C address 0x68\n")
            log.write("This robot uses measured timed-turn fallback values.\n")
    except OSError:
        pass
    robot._cal_show("CAL SKIP", "no gyro", "timed turns")
    _calibration = None
    _no_gyro = True
else:
    _no_gyro = False
    _calibration = robot.characterise(restart=True)
    robot._timer_stop()

if _calibration is not None:
    try:
        os.remove("calibration_done.py")
    except OSError:
        pass
    try:
        os.rename("calibration_attempt.py", "calibration_done.py")
    except OSError:
        pass
    robot._cal_show("CAL DONE", "saved", "load blocks")
elif not _no_gyro:
    robot._cal_show("CAL FAIL", "power retry", "see cal log")

while True:
    time.sleep(1)
