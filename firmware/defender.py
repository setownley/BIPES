# defender.py - Defender Mini for the classroom robot boards (MicroPython).
# Side-scrolling shooter on the onboard 72x40 OLED window.
#
# Entry points:
#   run(oled, btn, x0=28, y0=24, led=None)  - called by robot._play_game()
#   demo()                                  - standalone test from the REPL on a
#                                             board WITHOUT robot.py imported:
#                                             import defender; defender.demo()
#
# Controls: the ship auto-fires. TAP BOOT = move to the next altitude band
# (wraps around). Shoot the enemies before they reach you.
# Game over: tap = restart, hold ~2s = clear the saved high score.
# Exit: press RST (reboots to robot OS).
#
# High score persists in defender_hi.txt on flash.
# Gameplay is ported from the atomic14 ESP32-C3 single-button games: enemy
# every 700 ms, shot every 350 ms, 1 point per kill, an enemy reaching the
# ship in its band = game over.
import time
import random

# ---------------- playfield geometry (72x40 window) ----------------
W = 72
H = 40
BANDS = 3
NENEMY = 6
NSHOT = 6
SHIP_X = 3
SPAWN_MS = 700
FIRE_MS = 350
ENEMY_SPEED = 18.0
SHOT_SPEED = 40.0


def _band_y(band):
    return 8 + band * 10

# ---------------- shared tuning ----------------
FRAME_MS = 40          # ~25 fps target; oled.show() is the real throttle
MAX_STEP_MS = 50       # cap one physics step so a slow frame can't tunnel
HIT_PAUSE_MS = 900
WAVE_MSG_MS = 1400
HI_FILE = "defender_hi.txt"

# game-over hold to clear the high score
_HI_CLEAR_MS = 2000

# tiny 3x5 digits for the in-game score (the 8x8 font is too big)
_DIG = (
    (7, 5, 5, 5, 7), (2, 6, 2, 2, 7), (7, 1, 7, 4, 7), (7, 1, 7, 1, 7),
    (5, 5, 7, 1, 1), (7, 4, 7, 1, 7), (7, 4, 7, 5, 7), (7, 1, 1, 1, 1),
    (7, 5, 7, 5, 7), (7, 5, 7, 1, 7),
)


def _num(o, x, y, n, xor=False):
    """Draw integer n with 3x5 digits, top-left at (x, y)."""
    for ch in str(n):
        rows = _DIG[ord(ch) - 48]
        for r in range(5):
            bits = rows[r]
            for i in range(3):
                if bits & (4 >> i):
                    px = x + i
                    py = y + r
                    o.pixel(px, py, (0 if o.pixel(px, py) else 1) if xor else 1)
        x += 4


def _load_hi():
    try:
        with open(HI_FILE) as f:
            return int(f.read())
    except (OSError, ValueError):
        return 0


def _save_hi(v):
    try:
        with open(HI_FILE, "w") as f:
            f.write(str(v))
    except OSError:
        pass


class Game:
    def __init__(self, oled, btn, x0, y0, led):
        self.o = oled
        self.btn = btn
        self.x0 = x0
        self.y0 = y0
        self.led = led
        self.hi = _load_hi()
        self.score = 0
        # button state
        self.down = False
        self.pressed_at = 0
        self.tapped = False
        self.released = 0
        self.led_until = 0
        self.now = time.ticks_ms()
        self._setup()

    # ---------------- button ----------------
    def _poll(self):
        v = self.btn.value() == 0
        if v and not self.down:
            self.down = True
            self.pressed_at = self.now
            self.tapped = True
        elif (not v) and self.down:
            self.down = False
            d = time.ticks_diff(self.now, self.pressed_at)
            self.released = d if d > 0 else 1

    def take_tap(self):
        t = self.tapped
        self.tapped = False
        return t

    def take_release(self):
        v = self.released
        self.released = 0
        return v

    def held(self):
        return time.ticks_diff(self.now, self.pressed_at) if self.down else 0

    def clear_events(self):
        self.tapped = False
        self.released = 0

    def _led_set(self):
        if self.led is not None:
            self.led.value(0 if time.ticks_diff(self.led_until, self.now) > 0
                           else 1)

    def blink(self, ms):
        self.led_until = time.ticks_add(self.now, ms)

    # ---------------- drawing helpers ----------------
    def _screen(self, lines):
        """lines = list of (text, y) inside the 72x40 window; 8x8 font,
        9 chars max per line, centred."""
        o = self.o
        o.fill(0)
        for txt, y in lines:
            o.text(txt, self.x0 + (W - 8 * len(txt)) // 2, self.y0 + y, 1)
        o.show()

    def _wait(self, ms):
        """Idle for ms while keeping the button and LED serviced."""
        t0 = self.now
        while time.ticks_diff(self.now, t0) < ms:
            self.now = time.ticks_ms()
            self._poll()
            self._led_set()
            time.sleep_ms(15)

    def _setup(self):
        # [active, band, x]
        self.enemies = [[False, 0, 0.0] for _ in range(NENEMY)]
        self.shots = [[False, 0, 0.0] for _ in range(NSHOT)]

    def reset(self):
        self.score = 0
        self.band = 1
        self.spawn_timer = 0
        self.fire_timer = 0
        for e in self.enemies:
            e[0] = False
        for s in self.shots:
            s[0] = False

    def _spawn_enemy(self):
        for e in self.enemies:
            if not e[0]:
                e[0] = True
                e[1] = random.randint(0, BANDS - 1)
                e[2] = float(W - 5)
                return

    def _fire(self):
        for s in self.shots:
            if not s[0]:
                s[0] = True
                s[1] = self.band
                s[2] = float(SHIP_X + 5)
                return

    # ---------------- gameplay ----------------
    def update(self, dt_ms):
        """Returns 0 = keep playing, 2 = game over."""
        if self.take_tap():
            self.band = (self.band + 1) % BANDS
        self.take_release()

        self.spawn_timer += dt_ms
        if self.spawn_timer >= SPAWN_MS:
            self.spawn_timer = 0
            self._spawn_enemy()
        self.fire_timer += dt_ms
        if self.fire_timer >= FIRE_MS:
            self.fire_timer = 0
            self._fire()

        dt = dt_ms * 0.001
        emove = ENEMY_SPEED * dt
        smove = SHOT_SPEED * dt
        for e in self.enemies:
            if not e[0]:
                continue
            e[2] -= emove
            if e[2] <= SHIP_X + 2 and e[1] == self.band:
                return 2
            elif e[2] < 0:
                e[0] = False
        for s in self.shots:
            if not s[0]:
                continue
            s[2] += smove
            if s[2] > W:
                s[0] = False
        for e in self.enemies:
            if not e[0]:
                continue
            for s in self.shots:
                if s[0] and s[1] == e[1] and e[2] <= s[2] <= e[2] + 3:
                    s[0] = False
                    e[0] = False
                    self.score += 1
                    self.blink(60)
                    break
        return 0

    # ---------------- drawing ----------------
    def draw(self):
        o = self.o
        x0 = self.x0
        y0 = self.y0
        o.fill(0)
        o.fill_rect(x0 + SHIP_X, y0 + _band_y(self.band), 4, 3, 1)
        for e in self.enemies:
            if e[0]:
                o.rect(x0 + int(e[2]), y0 + _band_y(e[1]), 4, 3, 1)
        for s in self.shots:
            if s[0]:
                o.pixel(x0 + int(s[2]), y0 + _band_y(s[1]) + 1, 1)
        _num(o, x0 + 1, y0 + 1, self.score)
        o.show()

    # ---------------- top-level state machine ----------------
    def run(self):
        while True:                       # forever; RST exits
            # title
            self.clear_events()
            blink = True
            last = 0
            while True:
                self.now = time.ticks_ms()
                self._poll()
                self._led_set()
                if self.take_release():
                    break
                if time.ticks_diff(self.now, last) >= 400:
                    last = self.now
                    blink = not blink
                    self._screen([("DEFENDER", 2),
                                  ("HI %d" % self.hi, 16),
                                  ("TAP", 30) if blink else ("", 30)])
                time.sleep_ms(15)

            # play
            self.now = time.ticks_ms()
            self.reset()
            self.clear_events()
            lf = 0
            last_upd = self.now
            while True:
                self.now = time.ticks_ms()
                self._poll()
                self._led_set()
                dt = time.ticks_diff(self.now, last_upd)
                last_upd = self.now
                if dt > MAX_STEP_MS:
                    dt = MAX_STEP_MS
                if self.update(dt):
                    break
                if time.ticks_diff(self.now, lf) >= FRAME_MS:
                    lf = self.now
                    self.draw()
                time.sleep_ms(5)
            self.draw()                   # show the fatal frame briefly
            self.blink(350)
            self._wait(700)

            # game over
            if self.score > self.hi:
                self.hi = self.score
                _save_hi(self.hi)
            self.clear_events()
            cleared = False
            cleared_at = 0
            last = 0
            alt = False
            while True:
                self.now = time.ticks_ms()
                self._poll()
                self._led_set()
                if (not cleared) and self.held() >= _HI_CLEAR_MS:
                    self.hi = 0
                    _save_hi(0)
                    cleared = True
                    cleared_at = self.now
                    self.blink(200)
                rel = self.take_release()
                if 0 < rel < 600:
                    break
                if time.ticks_diff(self.now, last) >= 600:
                    last = self.now
                    alt = not alt
                    hi_line = "HI RESET" if (cleared and time.ticks_diff(
                        self.now, cleared_at) < 1200) else "HI %d" % self.hi
                    self._screen([("GAME OVER", 0),
                                  ("SC %d" % self.score, 12),
                                  (hi_line, 22),
                                  ("TAP" if alt else "HOLD=CLR", 32)])
                time.sleep_ms(15)


def run(oled, btn, x0=28, y0=24, led=None):
    """Start the game. Never returns - press RST to reboot to the robot OS."""
    Game(oled, btn, x0, y0, led).run()


def demo():
    """Standalone test on a board where robot.py has NOT been imported
    (fresh boot / raw REPL): import defender; defender.demo()"""
    from machine import Pin, I2C
    import ssd1306
    i2c = I2C(0, scl=Pin(6), sda=Pin(5), freq=400000)
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    btn = Pin(9, Pin.IN, Pin.PULL_UP)
    led = Pin(8, Pin.OUT)
    led.value(1)
    run(oled, btn, led=led)
