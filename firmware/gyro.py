"""Gyro turn angle for the classroom robot.

One job: how many degrees has the robot turned, left or right.

    + degrees = turned RIGHT (clockwise seen from above)
    - degrees = turned LEFT

Assumes the board lies flat. Pitch and roll are not exposed -- the robot
does not tilt, so they would only be three more things to get wrong.

HOW TO USE IT

    reset turn angle          <- immediately before the manoeuvre
    repeat until turn angle > 90:
        turn right
    stop

READ IT IN A LOOP. The angle is the turn RATE added up over time, so it only
advances when you read it. Read once, wait a second, read again, and the
whole second counts as one sample and the answer is wrong. Reading 20+ times
a second is plenty and costs nothing.

Over a few seconds this is accurate to about a degree. Over minutes it
wanders, which is why you reset before each manoeuvre rather than tracking
heading all the way round a maze.
"""
import time

from machine import I2C, Pin

_PWR_MGMT_1 = 0x6B
_GYRO_ZOUT_H = 0x47      # gyro Z high byte -- the only axis we need
_WHO_AM_I = 0x75

_GYRO_SCALE = 131.0      # LSB per deg/s at the default +/-250 deg/s range


class Gyro:
    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr

        # The chip boots asleep and returns zeros until this is cleared,
        # which looks exactly like a wiring fault.
        self.i2c.writeto_mem(addr, _PWR_MGMT_1, b'\x00')
        time.sleep_ms(100)

        self.angle = 0.0
        self._bias = 0.0
        self._last = time.ticks_us()
        self.calibrate()

    def _rate(self):
        """Turn rate in degrees per second. Positive = right."""
        d = self.i2c.readfrom_mem(self.addr, _GYRO_ZOUT_H, 2)
        v = (d[0] << 8) | d[1]
        if v > 32767:
            v -= 65536
        # The chip's positive Z is anticlockwise; negate so positive reads
        # as a right turn, which is what anyone driving a robot expects.
        return -v / _GYRO_SCALE

    def calibrate(self, samples=100):
        """Measure the resting offset. Keep the robot still.

        Every one of these chips reports a small non-zero rate when it is
        not moving. Uncorrected, that offset adds up into the angle and the
        robot thinks it is turning while sitting still. Half a second well
        spent.
        """
        total = 0.0
        for _ in range(samples):
            total += self._rate()
            time.sleep_ms(5)
        self._bias = total / samples
        self.angle = 0.0
        self._last = time.ticks_us()

    def update(self):
        now = time.ticks_us()
        dt = time.ticks_diff(now, self._last) / 1_000_000.0
        self._last = now

        # Ignore an absurd gap rather than adding a huge bogus step. This
        # happens if the angle has not been read for a while -- the turn
        # during that gap is lost either way, but a wild jump is worse than
        # a missed one.
        if 0 < dt < 0.5:
            self.angle += (self._rate() - self._bias) * dt
        return self.angle

    def reset(self):
        self.angle = 0.0
        self._last = time.ticks_us()

    def present(self):
        try:
            return self.i2c.readfrom_mem(self.addr, _WHO_AM_I, 1)[0] in (
                0x68, 0x70, 0x72)
        except Exception:
            return False


_gyro = None


def gyro_setup(sda=5, scl=6, addr=0x68):
    global _gyro
    i2c = I2C(0, sda=Pin(sda), scl=Pin(scl))
    _gyro = Gyro(i2c, addr)
    return _gyro


def gyro_turn():
    """Degrees turned since the last reset. + right, - left."""
    if _gyro is None:
        gyro_setup()
    return _gyro.update()


def gyro_reset():
    if _gyro is None:
        gyro_setup()
    else:
        _gyro.reset()
