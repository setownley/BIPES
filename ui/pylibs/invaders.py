# invaders.py - Tiny Invaders for the classroom robot boards (MicroPython).
# A classic fixed-shooter on the onboard 72x40 OLED window.
#
# Entry points:
#   run(oled, btn, x0=28, y0=24, led=None)  - called by robot._play_game()
#   demo()                                  - standalone test from the REPL on a
#                                             board WITHOUT robot.py imported:
#                                             import invaders; invaders.demo()
#
# Controls: cannon auto-fires and moves continuously. TAP BOOT = reverse
# direction (auto-reverses at the edges). Game over: tap = restart,
# hold ~2s = clear the saved high score. Exit: press RST (reboots to robot OS).
#
# High score persists in invaders_hi.txt on flash.
# Gameplay is a straight port of the Arduino build: 4x7 formation that steps
# down at the edges and speeds up as it thins, row scoring 30/20/10, four
# eroding bunkers (damaged by your shots, alien bombs, and marching aliens),
# bonus UFO worth 50-300, one player shot at a time, shot-vs-bomb collisions,
# waves that start lower with faster bombs, invasion = instant game over.

import time
import framebuf
import random

# ---------------- playfield geometry (72x40 window) ----------------
W = 72
H = 40
GROUND_Y = 39
UFO_Y = 0

COLS = 7
ROWS = 4
ALIEN_W = 5
ALIEN_H = 3
PITCH_X = 7
PITCH_Y = 5
STEP_DOWN = 2
TOP_START = 8
TOP_MAX = 12

NBUNK = 4
BUNK_W = 7
BUNK_H = 4
BUNK_Y = 29
BUNK_X = (6, 24, 42, 60)
BUNK_SHAPE = (0x7C, 0xFE, 0xFE, 0xC6)   # MSB = leftmost pixel

PLAY_W = 5
PLAY_H = 4
PLAY_Y = 35
INVADE_Y = PLAY_Y - 1

# ---------------- tuning (same values as the Arduino build) ----------------
FRAME_MS = 40          # ~25 fps target; oled.show() is the real throttle
PLAYER_MS = 34
BULLET_MS = 12
AUTOFIRE_MS = 170
MAX_BOMBS = 3
HIT_PAUSE_MS = 900
WAVE_MSG_MS = 1400
POPUP_MS = 800
UFO_MS = 40

ROW_PTS = (30, 20, 20, 10)
HI_FILE = "invaders_hi.txt"

# ---------------- sprites (5 wide, MSB = leftmost pixel) ----------------
def _fb(rows, w, h):
    b = bytearray(rows)
    return framebuf.FrameBuffer(b, w, h, framebuf.MONO_HLSB)

# type 0 top row / type 1 middle rows / type 2 bottom row, 2 frames each
_SPR = (
    (_fb(b"\x50\xF8\x88", 5, 3), _fb(b"\x50\xF8\x50", 5, 3)),
    (_fb(b"\x88\xF8\x50", 5, 3), _fb(b"\x50\xF8\xA8", 5, 3)),
    (_fb(b"\x70\xF8\xA8", 5, 3), _fb(b"\x70\xF8\x50", 5, 3)),
)
_ROW_TYPE = (0, 1, 1, 2)
_UFO = _fb(b"\x7C\xFE\x54", 7, 3)
_PLAYER = _fb(b"\x20\x70\xF8\xF8", 5, 4)

# game-over hold to clear the high score
_HI_CLEAR_MS = 2000


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
        # bunkers as tiny mutable framebuffers (1 byte per row)
        self.bbuf = [bytearray(BUNK_H) for _ in range(NBUNK)]
        self.bfb = [framebuf.FrameBuffer(b, BUNK_W, BUNK_H, framebuf.MONO_HLSB)
                    for b in self.bbuf]
        # button state
        self.down = False
        self.pressed_at = 0
        self.tapped = False
        self.released = 0
        self.led_until = 0
        self.now = time.ticks_ms()

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

    # ---------------- wave / state ----------------
    def init_wave(self, n):
        self.wave = n
        self.al = [[True] * COLS for _ in range(ROWS)]
        self.alive = ROWS * COLS
        drop = (n - 1) * STEP_DOWN
        if drop > TOP_MAX - TOP_START:
            drop = TOP_MAX - TOP_START
        self.fy = TOP_START + drop
        self.fx = (W - ((COLS - 1) * PITCH_X + ALIEN_W)) // 2
        self.fdir = 1
        self.frame = 0
        self._bounds()
        t = self.now
        self.next_step = time.ticks_add(t, self.step_ms())
        self.px = (W - PLAY_W) // 2
        self.pdir = 1
        self.next_pmove = t
        self.b_act = False
        self.bx = 0
        self.by = 0
        self.next_bul = t
        self.fire_at = time.ticks_add(t, 400)
        self.bombs = [[False, 0, 0] for _ in range(MAX_BOMBS)]
        self.next_bmove = t
        self.next_bdrop = time.ticks_add(t, 1200)
        self.ufo = False
        self.ufo_x = 0
        self.next_umove = t
        self.ufo_at = time.ticks_add(t, 8000 + random.randint(0, 8000))
        self.pop_until = t
        self.pop_x = 0
        self.pop_txt = ""
        for i in range(NBUNK):
            for r in range(BUNK_H):
                self.bbuf[i][r] = BUNK_SHAPE[r]

    def _bounds(self):
        self.min_c = COLS
        self.max_c = -1
        self.max_r = -1
        for r in range(ROWS):
            row = self.al[r]
            for c in range(COLS):
                if row[c]:
                    if c < self.min_c:
                        self.min_c = c
                    if c > self.max_c:
                        self.max_c = c
                    if r > self.max_r:
                        self.max_r = r

    def step_ms(self):
        t = 30 + self.alive * 14 - (self.wave - 1) * 8
        return t if t > 36 else 36

    # ---------------- bunkers ----------------
    def bunker_hit(self, x, y, from_above):
        if y < BUNK_Y or y >= BUNK_Y + BUNK_H:
            return False
        br = y - BUNK_Y
        for b in range(NBUNK):
            bx = BUNK_X[b]
            if x < bx or x >= bx + BUNK_W:
                continue
            i = x - bx
            fb = self.bfb[b]
            if not fb.pixel(i, br):
                return False
            fb.pixel(i, br, 0)
            if i > 0:
                fb.pixel(i - 1, br, 0)
            if i < BUNK_W - 1:
                fb.pixel(i + 1, br, 0)
            r2 = br + (1 if from_above else -1)
            if 0 <= r2 < BUNK_H:
                fb.pixel(i, r2, 0)
            return True
        return False

    def erode(self):
        if self.fy + self.max_r * PITCH_Y + ALIEN_H <= BUNK_Y:
            return
        for r in range(ROWS):
            row = self.al[r]
            ay = self.fy + r * PITCH_Y
            for c in range(COLS):
                if not row[c]:
                    continue
                ax = self.fx + c * PITCH_X
                for yy in range(ay, ay + ALIEN_H):
                    br = yy - BUNK_Y
                    if br < 0 or br >= BUNK_H:
                        continue
                    for b in range(NBUNK):
                        lo = ax if ax > BUNK_X[b] else BUNK_X[b]
                        hi = ax + ALIEN_W - 1
                        m = BUNK_X[b] + BUNK_W - 1
                        if hi > m:
                            hi = m
                        for xx in range(lo, hi + 1):
                            self.bfb[b].pixel(xx - BUNK_X[b], br, 0)

    # ---------------- gameplay updates ----------------
    def resolve_shot(self):
        self.b_act = False
        self.fire_at = time.ticks_add(self.now, AUTOFIRE_MS)

    def update_play(self):
        """Returns: 0 = keep playing, 1 = wave cleared, 2 = life lost,
        3 = game over (invaded)."""
        now = self.now
        if self.take_tap():
            self.pdir = -self.pdir
        self.take_release()
        if time.ticks_diff(now, self.next_pmove) >= 0:
            self.next_pmove = time.ticks_add(now, PLAYER_MS)
            self.px += self.pdir
            if self.px <= 0:
                self.px = 0
                self.pdir = 1
            if self.px >= W - PLAY_W:
                self.px = W - PLAY_W
                self.pdir = -1

        if (not self.b_act) and time.ticks_diff(now, self.fire_at) >= 0:
            self.b_act = True
            self.bx = self.px + PLAY_W // 2
            self.by = PLAY_Y - 1
            self.next_bul = now

        steps = 0
        while self.b_act and time.ticks_diff(now, self.next_bul) >= 0 \
                and steps < 6:
            steps += 1
            self.next_bul = time.ticks_add(self.next_bul, BULLET_MS)
            self.by -= 1
            if self.by < 0:
                self.resolve_shot()
                break
            if self.ufo and self.by <= UFO_Y + 2 and \
                    self.ufo_x <= self.bx < self.ufo_x + 7:
                bonus = 50 * random.randint(1, 6)
                self.score += bonus
                self.ufo = False
                self.ufo_at = time.ticks_add(now, 9000 + random.randint(0, 9000))
                self.pop_txt = str(bonus)
                self.pop_x = min(max(self.ufo_x, 0), W - 24)
                self.pop_until = time.ticks_add(now, POPUP_MS)
                self.blink(120)
                self.resolve_shot()
                break
            if self.bunker_hit(self.bx, self.by, False):
                self.resolve_shot()
                break
            hit = False
            for r in range(ROWS - 1, -1, -1):
                ay = self.fy + r * PITCH_Y
                if not (ay <= self.by < ay + ALIEN_H):
                    continue
                row = self.al[r]
                for c in range(COLS):
                    if not row[c]:
                        continue
                    ax = self.fx + c * PITCH_X
                    if ax <= self.bx < ax + ALIEN_W:
                        row[c] = False
                        self.alive -= 1
                        self.score += ROW_PTS[r]
                        self._bounds()
                        self.resolve_shot()
                        hit = True
                        break
                if hit:
                    break
            if hit:
                if self.alive == 0:
                    return 1
                break
            for bm in self.bombs:
                if bm[0] and abs(bm[1] - self.bx) <= 1 and \
                        bm[2] - 1 <= self.by <= bm[2] + 1:
                    bm[0] = False
                    self.resolve_shot()
                    break

        if time.ticks_diff(now, self.next_step) >= 0:
            self.next_step = time.ticks_add(now, self.step_ms())
            self.frame ^= 1
            left = self.fx + self.min_c * PITCH_X
            right = self.fx + self.max_c * PITCH_X + ALIEN_W - 1
            if (self.fdir > 0 and right + 1 > W - 1) or \
                    (self.fdir < 0 and left - 1 < 0):
                self.fy += STEP_DOWN
                self.fdir = -self.fdir
                if self.fy + self.max_r * PITCH_Y + ALIEN_H - 1 >= INVADE_Y:
                    return 3
            else:
                self.fx += self.fdir
            self.erode()

        if time.ticks_diff(now, self.next_bmove) >= 0:
            bms = 48 - (self.wave - 1) * 3
            if bms < 24:
                bms = 24
            self.next_bmove = time.ticks_add(now, bms)
            for bm in self.bombs:
                if not bm[0]:
                    continue
                bm[2] += 1
                tip = bm[2] + 1
                if tip > GROUND_Y:
                    bm[0] = False
                    continue
                if self.bunker_hit(bm[1], tip, True):
                    bm[0] = False
                    continue
                if tip >= PLAY_Y and self.px <= bm[1] < self.px + PLAY_W:
                    bm[0] = False
                    return 2

        if time.ticks_diff(now, self.next_bdrop) >= 0:
            gap = 950 - (self.wave - 1) * 70
            if gap < 380:
                gap = 380
            self.next_bdrop = time.ticks_add(
                now, gap // 2 + random.randint(0, gap))
            for bm in self.bombs:
                if bm[0]:
                    continue
                for _ in range(8):
                    c = random.randint(0, COLS - 1)
                    done = False
                    for r in range(ROWS - 1, -1, -1):
                        if self.al[r][c]:
                            bm[0] = True
                            bm[1] = self.fx + c * PITCH_X + ALIEN_W // 2
                            bm[2] = self.fy + r * PITCH_Y + ALIEN_H
                            done = True
                            break
                    if done:
                        break
                break

        if (not self.ufo) and time.ticks_diff(now, self.ufo_at) >= 0:
            self.ufo = True
            self.ufo_x = W
            self.next_umove = now
        if self.ufo and time.ticks_diff(now, self.next_umove) >= 0:
            self.next_umove = time.ticks_add(now, UFO_MS)
            self.ufo_x -= 1
            if self.ufo_x < -7:
                self.ufo = False
                self.ufo_at = time.ticks_add(now, 9000 + random.randint(0, 9000))
        return 0

    # ---------------- drawing ----------------
    def draw_play(self, hit_pause):
        o = self.o
        x0 = self.x0
        y0 = self.y0
        o.fill(0)
        o.hline(x0, y0 + GROUND_Y, W, 1)
        for i in range(3 if self.lives > 3 else self.lives):
            o.fill_rect(x0 + W - 3 - i * 4, y0, 3, 2, 1)
        for b in range(NBUNK):
            o.blit(self.bfb[b], x0 + BUNK_X[b], y0 + BUNK_Y, 0)
        for r in range(ROWS):
            row = self.al[r]
            spr = _SPR[_ROW_TYPE[r]][self.frame]
            ay = y0 + self.fy + r * PITCH_Y
            for c in range(COLS):
                if row[c]:
                    o.blit(spr, x0 + self.fx + c * PITCH_X, ay, 0)
        if self.ufo:
            o.blit(_UFO, x0 + self.ufo_x, y0 + UFO_Y, 0)
        if (not hit_pause) or (self.now // 120) & 1:
            o.blit(_PLAYER, x0 + self.px, y0 + PLAY_Y, 0)
        if self.b_act:
            o.vline(x0 + self.bx, y0 + self.by, 3, 1)
        for bm in self.bombs:
            if bm[0]:
                o.vline(x0 + bm[1], y0 + bm[2], 2, 1)
        if time.ticks_diff(self.pop_until, self.now) > 0:
            o.text(self.pop_txt, x0 + self.pop_x, y0 + 6, 1)
        o.show()

    def _screen(self, lines):
        """lines = list of (text, y) inside the 72x40 window; 8x8 font,
        9 chars max per line, centred."""
        o = self.o
        o.fill(0)
        for txt, y in lines:
            o.text(txt, self.x0 + (W - 8 * len(txt)) // 2, self.y0 + y, 1)
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
                    self._screen([("INVADERS", 2),
                                  ("HI %d" % self.hi, 16),
                                  ("TAP", 30) if blink else ("", 30)])
                time.sleep_ms(15)

            self.score = 0
            self.lives = 3
            wave = 1
            playing = True
            while playing:
                # wave splash
                self.init_wave(wave)
                self._screen([("WAVE %d" % wave, 8),
                              ("%d" % self.score, 24)])
                t0 = self.now
                while time.ticks_diff(self.now, t0) < WAVE_MSG_MS:
                    self.now = time.ticks_ms()
                    self._poll()
                    self._led_set()
                    time.sleep_ms(15)
                self.clear_events()
                # re-anchor timers after the splash
                self.init_wave(wave)

                # play
                lf = 0
                while True:
                    self.now = time.ticks_ms()
                    self._poll()
                    self._led_set()
                    ev = self.update_play()
                    if ev == 1:               # wave cleared
                        wave += 1
                        break
                    if ev == 3:               # invaded
                        playing = False
                        break
                    if ev == 2:               # life lost
                        self.blink(350)
                        self.lives -= 1
                        for bm in self.bombs:
                            bm[0] = False
                        self.b_act = False
                        if self.lives == 0:
                            playing = False
                            break
                        self.px = (W - PLAY_W) // 2
                        t0 = self.now
                        while time.ticks_diff(self.now, t0) < HIT_PAUSE_MS:
                            self.now = time.ticks_ms()
                            self._poll()
                            self._led_set()
                            if time.ticks_diff(self.now, lf) >= FRAME_MS:
                                lf = self.now
                                self.draw_play(True)
                            time.sleep_ms(5)
                        self.clear_events()
                        t = self.now
                        self.next_pmove = t
                        self.next_step = time.ticks_add(t, self.step_ms())
                        self.next_bmove = t
                        self.next_bdrop = time.ticks_add(t, 800)
                        self.fire_at = time.ticks_add(t, 300)
                        continue
                    if time.ticks_diff(self.now, lf) >= FRAME_MS:
                        lf = self.now
                        self.draw_play(False)
                    time.sleep_ms(5)

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
    (fresh boot / raw REPL): import invaders; invaders.demo()"""
    from machine import Pin, I2C
    import ssd1306
    i2c = I2C(0, scl=Pin(6), sda=Pin(5), freq=400000)
    oled = ssd1306.SSD1306_I2C(128, 64, i2c)
    btn = Pin(9, Pin.IN, Pin.PULL_UP)
    led = Pin(8, Pin.OUT)
    led.value(1)
    run(oled, btn, led=led)
