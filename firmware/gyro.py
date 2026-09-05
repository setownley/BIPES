"""Gyro turn angle for the classroom robot.

One job: how many degrees has the robot turned, left or right.

    + degrees = turned RIGHT (clockwise seen from above)
    - degrees = turned LEFT

Assumes the board lies flat. Pitch and roll are not exposed -- the robot does
not tilt, so they would only be more things to get wrong.

    reset turn angle
    repeat 4 times:
        turn right until turn angle > 90
        reset turn angle

WHY A BACKGROUND TIMER
    The angle is the turn RATE added up over time, so it needs sampling
    steadily whether or not anyone is reading it. An earlier version only
    advanced when the block was read, which meant a program like

        reset angle / read angle / wait 1 second

    took one instantaneous sample and multiplied it by the whole second.
    Turning 90 degrees read as about 8. That is a trap, not a lesson: the
    natural way to write the program gave the wrong answer.

    So a timer samples at 50Hz in the background and the read block just
    returns the running total. Poll it once a second or a thousand times a
    second -- same answer.

SHARING THE I2C BUS
    The OLED and the ToF sensor sit on the same bus as the gyro. A timer
    callback firing in the middle of someone else's transaction corrupts
    both. The lock below makes the timer SKIP its sample when the bus is
    busy rather than wait for it: a missed sample costs a fraction of a
    degree, a collision costs a garbled display and a wrong distance.

    Foreground code that shares the bus should wrap its transactions:

        with gyro_bus():
            ...i2c work...

    The timer only exists between gyro_setup() and gyro_stop(). Nothing runs
    in the background until a program asks for it.
"""
import time

from machine import I2C, Pin, Timer

_PWR_MGMT_1 = 0x6B
_GYRO_ZOUT_H = 0x47      # gyro Z high byte -- the only axis we need
_WHO_AM_I = 0x75

_GYRO_SCALE = 131.0      # LSB per deg/s at the default +/-250 deg/s range
_SAMPLE_MS = 20          # 50Hz. Fast enough for a 90 degree turn, light
                         # enough to leave the bus mostly free.

# Timer 1, NOT 0. robot.py's Robot OS already claims Timer(0) for its
# background tick, and machine.Timer(0) twice means whichever calls init()
# last silently takes the hardware over -- the OS loop would simply stop
# with no error. robot.py's own comment reserves 1 for this.
_TIMER_ID = 1


class _BusLock:
    """Cooperative flag, not a real mutex.

    MicroPython has no threads here; the danger is a timer interrupt landing
    mid-transaction. A plain flag is enough because the timer checks it and
    gives up immediately rather than waiting.
    """

    def __init__(self):
        self.busy = False

    def __enter__(self):
        self.busy = True
        return self

    def __exit__(self, *a):
        self.busy = False
        return False


class Gyro:
    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr
        self.lock = _BusLock()

        # The chip boots asleep and returns zeros until this is cleared,
        # which looks exactly like a wiring fault.
        self.i2c.writeto_mem(addr, _PWR_MGMT_1, b'\x00')
        time.sleep_ms(100)

        self.angle = 0.0
        self._bias = 0.0
        self._last = time.ticks_us()
        self._skipped = 0
        self._timer = None

        self.calibrate()
        self.start()

    # ---- reading ---------------------------------------------------------

    def _rate(self):
        """Turn rate in degrees per second. Positive = right."""
        d = self.i2c.readfrom_mem(self.addr, _GYRO_ZOUT_H, 2)
        v = (d[0] << 8) | d[1]
        if v > 32767:
            v -= 65536
        # The chip's positive Z is anticlockwise; negate so positive reads as
        # a right turn, which is what anyone driving a robot expects.
        return -v / _GYRO_SCALE

    def calibrate(self, samples=100):
        """Measure the resting offset. Keep the robot still.

        Every one of these chips reports a small non-zero rate while sitting
        still. Uncorrected it adds up into the angle and the robot believes
        it is turning when it is not.
        """
        was_running = self._timer is not None
        self.stop()

        total = 0.0
        for _ in range(samples):
            total += self._rate()
            time.sleep_ms(5)
        self._bias = total / samples

        self.angle = 0.0
        self._last = time.ticks_us()
        if was_running:
            self.start()

    # ---- the background sampler -----------------------------------------

    def _tick(self, t):
        # Someone else is mid-transaction. Skip rather than interleave.
        if self.lock.busy:
            self._skipped += 1
            return
        try:
            with self.lock:
                rate = self._rate()
            now = time.ticks_us()
            dt = time.ticks_diff(now, self._last) / 1_000_000.0
            self._last = now
            # A gap this large means the timer was starved; count it anyway,
            # since discarding it silently loses real rotation. Anything
            # beyond a second is absurd and better dropped.
            if 0 < dt < 1.0:
                self.angle += (rate - self._bias) * dt
        except Exception:
            # A bus glitch must not kill the timer. Losing one sample is
            # recoverable; losing the sampler is not.
            self._skipped += 1

    def start(self):
        if self._timer is not None:
            return
        self._last = time.ticks_us()
        self._timer = Timer(_TIMER_ID)
        self._timer.init(period=_SAMPLE_MS, mode=Timer.PERIODIC,
                         callback=self._tick)

    def stop(self):
        """Stop sampling and release the timer."""
        if self._timer is not None:
            self._timer.deinit()
            self._timer = None

    # ---- what the blocks call -------------------------------------------

    def read(self):
        # One decimal place. The sensor is not accurate to more than that,
        # and a student watching -8.000000 scroll past learns nothing from
        # the extra six digits.
        return round(self.angle, 1)

    def reset(self):
        self.angle = 0.0
        self._last = time.ticks_us()

    def present(self):
        try:
            with self.lock:
                who = self.i2c.readfrom_mem(self.addr, _WHO_AM_I, 1)[0]
            return who in (0x68, 0x70, 0x72)
        except Exception:
            return False


_gyro = None


def gyro_setup(sda=5, scl=6, addr=0x68, bus=0):
    """Wake the gyro, calibrate it, and start sampling in the background.

    bus is the I2C peripheral number. It has to be a parameter rather than
    hardcoded, or the block's I2C dropdown does nothing and a student who
    picks bus 1 silently gets bus 0.
    """
    global _gyro
    if _gyro is not None:
        _gyro.stop()
    i2c = I2C(bus, sda=Pin(sda), scl=Pin(scl))
    _gyro = Gyro(i2c, addr)
    return _gyro


def gyro_stop():
    """Stop the background sampler and free the timer."""
    global _gyro
    if _gyro is not None:
        _gyro.stop()
        _gyro = None


def gyro_turn():
    """Degrees turned since the last reset, to 0.1 deg. + right, - left."""
    if _gyro is None:
        gyro_setup()
    return _gyro.read()


def gyro_reset():
    if _gyro is None:
        gyro_setup()
    else:
        _gyro.reset()


def gyro_bus():
    """Context manager for foreground I2C work on the shared bus.

        with gyro_bus():
            oled.show()

    Without this, an OLED or ToF transaction can be interrupted mid-way by
    the sampler and both readings corrupt.
    """
    if _gyro is None:
        gyro_setup()
    return _gyro.lock


def gyro_skipped():
    """Samples dropped to bus contention. Should be a small fraction."""
    return 0 if _gyro is None else _gyro._skipped
