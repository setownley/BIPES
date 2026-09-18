/*
 * Games category for the classroom fork: split out of queue.js because the
 * embedded standalone games (defender in particular, ~14KB of Python source
 * as a JS string) were about to nearly double that file's size. Everything
 * Games-related - the toolbox category injection and all block/generator
 * pairs - lives here instead, including the standalone twins of Invaders and
 * Snake added alongside Defender's: this file is meant to keep growing as
 * the game library grows, so it (not queue.js) is where a new game goes.
 * Load order versus queue.js does not matter:
 * this file wraps whatever xhrGET currently is, the same way queue.js wraps
 * the true original, so the two layers chain correctly either way. It is
 * loaded after queue.js in index.html purely by convention (Games is
 * logically "on top of" the teaching blocks).
 *
 * classroomToolboxFailed is defined by queue.js as a script-level var, which
 * makes it a genuine global - reused here rather than redefined, so both
 * files report failures through the same notification path. Falls back to a
 * minimal local version if queue.js is ever missing or fails to load, so a
 * broken load order degrades to a console message instead of a silent
 * ReferenceError killing every game block.
 */
if (typeof classroomToolboxFailed !== 'function') {
    var classroomToolboxFailed = function (which, why, err) {
        console.error('Classroom toolbox: the ' + which + ' could not be added (' + why + ').', err || '');
    };
}

/* The Games category is injected here at runtime, the same pattern queue.js
   uses for VL53L0X and the gyro. See queue.js's own comment for the
   served-vs-file:// response shape this accounts for. */
if (typeof xhrGET === 'function') {
    var classroomGamesOriginalXhrGET = xhrGET;

    xhrGET = function(filename, responsetype, onsuccess, onfail) {
        return classroomGamesOriginalXhrGET(filename, responsetype, function(response) {
            if (responsetype === 'document' && /toolbox\/esp32\.xml/i.test(filename)) {
                var doc = response.nodeType === 9 ? response : response.ownerDocument;

                /* Games is a top-level category of its own, not nested inside
                   CAT_SENSORS like the ToF/gyro ones - it sits at the bottom
                   of the toolbox, below MicroPython. Anchor off the first
                   category literally named "micropython" (the big
                   reference-doc wrapper right above the closing tag) rather
                   than response.documentElement: that differs in shape
                   between the served XMLDocument and the baked file://
                   element, but parentNode reaches the same toolbox root
                   either way. */
                try {
                    if (!doc || typeof doc.createElement !== 'function')
                        throw new Error('no owning document for the toolbox XML');

                    var allCategories = response.querySelectorAll('category');
                    var micropython = null;
                    for (var g = 0; g < allCategories.length; g++) {
                        if (allCategories[g].getAttribute('name') === 'micropython') {
                            micropython = allCategories[g];
                            break;
                        }
                    }
                    if (!micropython || !micropython.parentNode)
                        throw new Error('no MicroPython category to anchor below');

                    /* One block per game. Add a new game by adding its block
                       type to this array - nothing else here needs to
                       change. Finds the Games category if an earlier pass
                       already created one and tops up whatever is missing,
                       rather than assuming all-or-nothing, so a growing
                       gameBlocks list can never end up with two Games
                       categories side by side. */
                    var gameBlocks = ['play_invaders_standalone', 'play_snake_standalone', 'play_defender_standalone', 'play_frogger_standalone'];
                    var retiredGameBlocks = ['play_invaders', 'play_snake', 'play_defender'];
                    var hasBlock = function (t) { return !!response.querySelector('block[type="' + t + '"]'); };

                    /* Older toolboxes and an already-built Games category can
                       still contain the file-based twins. Remove those menu
                       entries explicitly; their block definitions remain so
                       old saved projects continue to open. */
                    retiredGameBlocks.forEach(function (t) {
                        var oldBlocks = response.querySelectorAll('block[type="' + t + '"]');
                        for (var ob = oldBlocks.length - 1; ob >= 0; ob--) {
                            if (oldBlocks[ob].parentNode)
                                oldBlocks[ob].parentNode.removeChild(oldBlocks[ob]);
                        }
                    });

                    if (!gameBlocks.every(hasBlock)) {
                        var gamesCategory = null;
                        for (var gc = 0; gc < allCategories.length; gc++) {
                            if (allCategories[gc].getAttribute('name') === 'Games') {
                                gamesCategory = allCategories[gc];
                                break;
                            }
                        }
                        if (!gamesCategory) {
                            gamesCategory = doc.createElement('category');
                            gamesCategory.setAttribute('name', 'Games');
                            gamesCategory.setAttribute('colour', '290');
                            micropython.parentNode.appendChild(gamesCategory);
                        }

                        gameBlocks.forEach(function (t) {
                            if (hasBlock(t)) return;   // already there
                            var b = doc.createElement('block');
                            b.setAttribute('type', t);
                            gamesCategory.appendChild(b);
                        });

                        if (!gameBlocks.every(hasBlock))
                            throw new Error('category attached but not readable back');
                    }
                } catch (e) {
                    classroomToolboxFailed('Games blocks', e.message, e);
                }
            }
            onsuccess(response);
        }, onfail);
    };
}

window.addEventListener('load', function () {
    if (typeof Blockly === 'undefined' || typeof Blockly.Python === 'undefined') return;

    /* Games category, starting with Invaders. One block, no fields beyond the
       I2C wiring: drop it in and the game starts, matching firmware/invaders.py.
       No next-statement connector on purpose - invaders.run() never returns,
       so anything placed after it would be dead code. */
    Blockly.Blocks['play_invaders'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Play Invaders');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/invaders.jpg", 55, 55, "*"));
            this.appendDummyInput()
                // 5/6, not 0/0: this is the OLED's actual bus on every
                // classroom robot (robot.py hardcodes the same pins). 0/0
                // isn't a safe placeholder here the way it is on the ToF and
                // gyro blocks - passing the same pin for SDA and SCL crashes
                // the whole board (see the ValueError guard below).
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            this.setTooltip('Start the Invaders game on the OLED. Tap BOOT to reverse the cannon. This block never finishes - press RST on the board to get back to your program. Anything after it will not run.');
        }
    };

    Blockly.Python['play_invaders'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        Blockly.Python.definitions_['import_invaders'] =
            'import invaders\n' +
            'from machine import Pin, I2C\n' +
            'import ssd1306';

        // Stop anything that touches I2C in the background. Each guarded
        // separately so a board with only one of them still works.
        //
        // The SDA == SCL guard exists because ESP-IDF's i2c_set_pin() rejects
        // that combination at the C level, not the Python one: instead of a
        // catchable exception it is a Guru Meditation Error that panics and
        // reboots the whole board. Raising here trades a board crash for a
        // message a student can actually read on reset.
        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.os_timer(False)\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Play Invaders: SDA and SCL cannot be the same pin")\n' +
                '_inv_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_inv_oled = ssd1306.SSD1306_I2C(128, 64, _inv_i2c)\n' +
                'invaders.run(_inv_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=Pin(8, Pin.OUT))\n';
    };

    /* Standalone twin of Invaders above: the whole game embedded as Python
       source text via definitions_, so it runs on a board with nothing on it
       but ssd1306.py. Nested inside a single _play_invaders() function, so it
       creates exactly one global. Keep both - the file-based block above is
       for boards that already have invaders.py; this one is for a board
       fresh off the flasher. */
    var INVADERS_SRC = [
        "def _play_invaders(oled, btn, x0=28, y0=24, led=None):",
        "    # Whole game nested here, so it creates exactly one global.",
        "    import time",
        "    import framebuf",
        "    import random",
        "",
        "    # ---------------- playfield geometry (72x40 window) ----------------",
        "    W = 72",
        "    H = 40",
        "    GROUND_Y = 39",
        "    UFO_Y = 0",
        "",
        "    COLS = 7",
        "    ROWS = 4",
        "    ALIEN_W = 5",
        "    ALIEN_H = 3",
        "    PITCH_X = 7",
        "    PITCH_Y = 5",
        "    STEP_DOWN = 2",
        "    TOP_START = 8",
        "    TOP_MAX = 12",
        "",
        "    NBUNK = 4",
        "    BUNK_W = 7",
        "    BUNK_H = 4",
        "    BUNK_Y = 29",
        "    BUNK_X = (6, 24, 42, 60)",
        "    BUNK_SHAPE = (0x7C, 0xFE, 0xFE, 0xC6)   # MSB = leftmost pixel",
        "",
        "    PLAY_W = 5",
        "    PLAY_H = 4",
        "    PLAY_Y = 35",
        "    INVADE_Y = PLAY_Y - 1",
        "",
        "    # ---------------- tuning (same values as the Arduino build) ----------------",
        "    FRAME_MS = 40          # ~25 fps target; oled.show() is the real throttle",
        "    PLAYER_MS = 34",
        "    BULLET_MS = 12",
        "    AUTOFIRE_MS = 170",
        "    MAX_BOMBS = 3",
        "    HIT_PAUSE_MS = 900",
        "    WAVE_MSG_MS = 1400",
        "    POPUP_MS = 800",
        "    UFO_MS = 40",
        "",
        "    ROW_PTS = (30, 20, 20, 10)",
        "    HI_FILE = \"invaders_hi.txt\"",
        "",
        "    # ---------------- sprites (5 wide, MSB = leftmost pixel) ----------------",
        "    def _fb(rows, w, h):",
        "        b = bytearray(rows)",
        "        return framebuf.FrameBuffer(b, w, h, framebuf.MONO_HLSB)",
        "",
        "    # type 0 top row / type 1 middle rows / type 2 bottom row, 2 frames each",
        "    _SPR = (",
        "        (_fb(b\"\\x50\\xF8\\x88\", 5, 3), _fb(b\"\\x50\\xF8\\x50\", 5, 3)),",
        "        (_fb(b\"\\x88\\xF8\\x50\", 5, 3), _fb(b\"\\x50\\xF8\\xA8\", 5, 3)),",
        "        (_fb(b\"\\x70\\xF8\\xA8\", 5, 3), _fb(b\"\\x70\\xF8\\x50\", 5, 3)),",
        "    )",
        "    _ROW_TYPE = (0, 1, 1, 2)",
        "    _UFO = _fb(b\"\\x7C\\xFE\\x54\", 7, 3)",
        "    _PLAYER = _fb(b\"\\x20\\x70\\xF8\\xF8\", 5, 4)",
        "",
        "    # game-over hold to clear the high score",
        "    _HI_CLEAR_MS = 2000",
        "",
        "",
        "    def _load_hi():",
        "        try:",
        "            with open(HI_FILE) as f:",
        "                return int(f.read())",
        "        except (OSError, ValueError):",
        "            return 0",
        "",
        "",
        "    def _save_hi(v):",
        "        try:",
        "            with open(HI_FILE, \"w\") as f:",
        "                f.write(str(v))",
        "        except OSError:",
        "            pass",
        "",
        "",
        "    class Game:",
        "        def __init__(self, oled, btn, x0, y0, led):",
        "            self.o = oled",
        "            self.btn = btn",
        "            self.x0 = x0",
        "            self.y0 = y0",
        "            self.led = led",
        "            self.hi = _load_hi()",
        "            # bunkers as tiny mutable framebuffers (1 byte per row)",
        "            self.bbuf = [bytearray(BUNK_H) for _ in range(NBUNK)]",
        "            self.bfb = [framebuf.FrameBuffer(b, BUNK_W, BUNK_H, framebuf.MONO_HLSB)",
        "                        for b in self.bbuf]",
        "            # button state",
        "            self.down = False",
        "            self.pressed_at = 0",
        "            self.tapped = False",
        "            self.released = 0",
        "            self.led_until = 0",
        "            self.now = time.ticks_ms()",
        "",
        "        # ---------------- button ----------------",
        "        def _poll(self):",
        "            v = self.btn.value() == 0",
        "            if v and not self.down:",
        "                self.down = True",
        "                self.pressed_at = self.now",
        "                self.tapped = True",
        "            elif (not v) and self.down:",
        "                self.down = False",
        "                d = time.ticks_diff(self.now, self.pressed_at)",
        "                self.released = d if d > 0 else 1",
        "",
        "        def take_tap(self):",
        "            t = self.tapped",
        "            self.tapped = False",
        "            return t",
        "",
        "        def take_release(self):",
        "            v = self.released",
        "            self.released = 0",
        "            return v",
        "",
        "        def held(self):",
        "            return time.ticks_diff(self.now, self.pressed_at) if self.down else 0",
        "",
        "        def clear_events(self):",
        "            self.tapped = False",
        "            self.released = 0",
        "",
        "        def _led_set(self):",
        "            if self.led is not None:",
        "                self.led.value(0 if time.ticks_diff(self.led_until, self.now) > 0",
        "                               else 1)",
        "",
        "        def blink(self, ms):",
        "            self.led_until = time.ticks_add(self.now, ms)",
        "",
        "        # ---------------- wave / state ----------------",
        "        def init_wave(self, n):",
        "            self.wave = n",
        "            self.al = [[True] * COLS for _ in range(ROWS)]",
        "            self.alive = ROWS * COLS",
        "            drop = (n - 1) * STEP_DOWN",
        "            if drop > TOP_MAX - TOP_START:",
        "                drop = TOP_MAX - TOP_START",
        "            self.fy = TOP_START + drop",
        "            self.fx = (W - ((COLS - 1) * PITCH_X + ALIEN_W)) // 2",
        "            self.fdir = 1",
        "            self.frame = 0",
        "            self._bounds()",
        "            t = self.now",
        "            self.next_step = time.ticks_add(t, self.step_ms())",
        "            self.px = (W - PLAY_W) // 2",
        "            self.pdir = 1",
        "            self.next_pmove = t",
        "            self.b_act = False",
        "            self.bx = 0",
        "            self.by = 0",
        "            self.next_bul = t",
        "            self.fire_at = time.ticks_add(t, 400)",
        "            self.bombs = [[False, 0, 0] for _ in range(MAX_BOMBS)]",
        "            self.next_bmove = t",
        "            self.next_bdrop = time.ticks_add(t, 1200)",
        "            self.ufo = False",
        "            self.ufo_x = 0",
        "            self.next_umove = t",
        "            self.ufo_at = time.ticks_add(t, 8000 + random.randint(0, 8000))",
        "            self.pop_until = t",
        "            self.pop_x = 0",
        "            self.pop_txt = \"\"",
        "            for i in range(NBUNK):",
        "                for r in range(BUNK_H):",
        "                    self.bbuf[i][r] = BUNK_SHAPE[r]",
        "",
        "        def _bounds(self):",
        "            self.min_c = COLS",
        "            self.max_c = -1",
        "            self.max_r = -1",
        "            for r in range(ROWS):",
        "                row = self.al[r]",
        "                for c in range(COLS):",
        "                    if row[c]:",
        "                        if c < self.min_c:",
        "                            self.min_c = c",
        "                        if c > self.max_c:",
        "                            self.max_c = c",
        "                        if r > self.max_r:",
        "                            self.max_r = r",
        "",
        "        def step_ms(self):",
        "            t = 30 + self.alive * 14 - (self.wave - 1) * 8",
        "            return t if t > 36 else 36",
        "",
        "        # ---------------- bunkers ----------------",
        "        def bunker_hit(self, x, y, from_above):",
        "            if y < BUNK_Y or y >= BUNK_Y + BUNK_H:",
        "                return False",
        "            br = y - BUNK_Y",
        "            for b in range(NBUNK):",
        "                bx = BUNK_X[b]",
        "                if x < bx or x >= bx + BUNK_W:",
        "                    continue",
        "                i = x - bx",
        "                fb = self.bfb[b]",
        "                if not fb.pixel(i, br):",
        "                    return False",
        "                fb.pixel(i, br, 0)",
        "                if i > 0:",
        "                    fb.pixel(i - 1, br, 0)",
        "                if i < BUNK_W - 1:",
        "                    fb.pixel(i + 1, br, 0)",
        "                r2 = br + (1 if from_above else -1)",
        "                if 0 <= r2 < BUNK_H:",
        "                    fb.pixel(i, r2, 0)",
        "                return True",
        "            return False",
        "",
        "        def erode(self):",
        "            if self.fy + self.max_r * PITCH_Y + ALIEN_H <= BUNK_Y:",
        "                return",
        "            for r in range(ROWS):",
        "                row = self.al[r]",
        "                ay = self.fy + r * PITCH_Y",
        "                for c in range(COLS):",
        "                    if not row[c]:",
        "                        continue",
        "                    ax = self.fx + c * PITCH_X",
        "                    for yy in range(ay, ay + ALIEN_H):",
        "                        br = yy - BUNK_Y",
        "                        if br < 0 or br >= BUNK_H:",
        "                            continue",
        "                        for b in range(NBUNK):",
        "                            lo = ax if ax > BUNK_X[b] else BUNK_X[b]",
        "                            hi = ax + ALIEN_W - 1",
        "                            m = BUNK_X[b] + BUNK_W - 1",
        "                            if hi > m:",
        "                                hi = m",
        "                            for xx in range(lo, hi + 1):",
        "                                self.bfb[b].pixel(xx - BUNK_X[b], br, 0)",
        "",
        "        # ---------------- gameplay updates ----------------",
        "        def resolve_shot(self):",
        "            self.b_act = False",
        "            self.fire_at = time.ticks_add(self.now, AUTOFIRE_MS)",
        "",
        "        def update_play(self):",
        "            \"\"\"Returns: 0 = keep playing, 1 = wave cleared, 2 = life lost,",
        "            3 = game over (invaded).\"\"\"",
        "            now = self.now",
        "            if self.take_tap():",
        "                self.pdir = -self.pdir",
        "            self.take_release()",
        "            if time.ticks_diff(now, self.next_pmove) >= 0:",
        "                self.next_pmove = time.ticks_add(now, PLAYER_MS)",
        "                self.px += self.pdir",
        "                if self.px <= 0:",
        "                    self.px = 0",
        "                    self.pdir = 1",
        "                if self.px >= W - PLAY_W:",
        "                    self.px = W - PLAY_W",
        "                    self.pdir = -1",
        "",
        "            if (not self.b_act) and time.ticks_diff(now, self.fire_at) >= 0:",
        "                self.b_act = True",
        "                self.bx = self.px + PLAY_W // 2",
        "                self.by = PLAY_Y - 1",
        "                self.next_bul = now",
        "",
        "            steps = 0",
        "            while self.b_act and time.ticks_diff(now, self.next_bul) >= 0 \\",
        "                    and steps < 6:",
        "                steps += 1",
        "                self.next_bul = time.ticks_add(self.next_bul, BULLET_MS)",
        "                self.by -= 1",
        "                if self.by < 0:",
        "                    self.resolve_shot()",
        "                    break",
        "                if self.ufo and self.by <= UFO_Y + 2 and \\",
        "                        self.ufo_x <= self.bx < self.ufo_x + 7:",
        "                    bonus = 50 * random.randint(1, 6)",
        "                    self.score += bonus",
        "                    self.ufo = False",
        "                    self.ufo_at = time.ticks_add(now, 9000 + random.randint(0, 9000))",
        "                    self.pop_txt = str(bonus)",
        "                    self.pop_x = min(max(self.ufo_x, 0), W - 24)",
        "                    self.pop_until = time.ticks_add(now, POPUP_MS)",
        "                    self.blink(120)",
        "                    self.resolve_shot()",
        "                    break",
        "                if self.bunker_hit(self.bx, self.by, False):",
        "                    self.resolve_shot()",
        "                    break",
        "                hit = False",
        "                for r in range(ROWS - 1, -1, -1):",
        "                    ay = self.fy + r * PITCH_Y",
        "                    if not (ay <= self.by < ay + ALIEN_H):",
        "                        continue",
        "                    row = self.al[r]",
        "                    for c in range(COLS):",
        "                        if not row[c]:",
        "                            continue",
        "                        ax = self.fx + c * PITCH_X",
        "                        if ax <= self.bx < ax + ALIEN_W:",
        "                            row[c] = False",
        "                            self.alive -= 1",
        "                            self.score += ROW_PTS[r]",
        "                            self._bounds()",
        "                            self.resolve_shot()",
        "                            hit = True",
        "                            break",
        "                    if hit:",
        "                        break",
        "                if hit:",
        "                    if self.alive == 0:",
        "                        return 1",
        "                    break",
        "                for bm in self.bombs:",
        "                    if bm[0] and abs(bm[1] - self.bx) <= 1 and \\",
        "                            bm[2] - 1 <= self.by <= bm[2] + 1:",
        "                        bm[0] = False",
        "                        self.resolve_shot()",
        "                        break",
        "",
        "            if time.ticks_diff(now, self.next_step) >= 0:",
        "                self.next_step = time.ticks_add(now, self.step_ms())",
        "                self.frame ^= 1",
        "                left = self.fx + self.min_c * PITCH_X",
        "                right = self.fx + self.max_c * PITCH_X + ALIEN_W - 1",
        "                if (self.fdir > 0 and right + 1 > W - 1) or \\",
        "                        (self.fdir < 0 and left - 1 < 0):",
        "                    self.fy += STEP_DOWN",
        "                    self.fdir = -self.fdir",
        "                    if self.fy + self.max_r * PITCH_Y + ALIEN_H - 1 >= INVADE_Y:",
        "                        return 3",
        "                else:",
        "                    self.fx += self.fdir",
        "                self.erode()",
        "",
        "            if time.ticks_diff(now, self.next_bmove) >= 0:",
        "                bms = 48 - (self.wave - 1) * 3",
        "                if bms < 24:",
        "                    bms = 24",
        "                self.next_bmove = time.ticks_add(now, bms)",
        "                for bm in self.bombs:",
        "                    if not bm[0]:",
        "                        continue",
        "                    bm[2] += 1",
        "                    tip = bm[2] + 1",
        "                    if tip > GROUND_Y:",
        "                        bm[0] = False",
        "                        continue",
        "                    if self.bunker_hit(bm[1], tip, True):",
        "                        bm[0] = False",
        "                        continue",
        "                    if tip >= PLAY_Y and self.px <= bm[1] < self.px + PLAY_W:",
        "                        bm[0] = False",
        "                        return 2",
        "",
        "            if time.ticks_diff(now, self.next_bdrop) >= 0:",
        "                gap = 950 - (self.wave - 1) * 70",
        "                if gap < 380:",
        "                    gap = 380",
        "                self.next_bdrop = time.ticks_add(",
        "                    now, gap // 2 + random.randint(0, gap))",
        "                for bm in self.bombs:",
        "                    if bm[0]:",
        "                        continue",
        "                    for _ in range(8):",
        "                        c = random.randint(0, COLS - 1)",
        "                        done = False",
        "                        for r in range(ROWS - 1, -1, -1):",
        "                            if self.al[r][c]:",
        "                                bm[0] = True",
        "                                bm[1] = self.fx + c * PITCH_X + ALIEN_W // 2",
        "                                bm[2] = self.fy + r * PITCH_Y + ALIEN_H",
        "                                done = True",
        "                                break",
        "                        if done:",
        "                            break",
        "                    break",
        "",
        "            if (not self.ufo) and time.ticks_diff(now, self.ufo_at) >= 0:",
        "                self.ufo = True",
        "                self.ufo_x = W",
        "                self.next_umove = now",
        "            if self.ufo and time.ticks_diff(now, self.next_umove) >= 0:",
        "                self.next_umove = time.ticks_add(now, UFO_MS)",
        "                self.ufo_x -= 1",
        "                if self.ufo_x < -7:",
        "                    self.ufo = False",
        "                    self.ufo_at = time.ticks_add(now, 9000 + random.randint(0, 9000))",
        "            return 0",
        "",
        "        # ---------------- drawing ----------------",
        "        def draw_play(self, hit_pause):",
        "            o = self.o",
        "            x0 = self.x0",
        "            y0 = self.y0",
        "            o.fill(0)",
        "            o.hline(x0, y0 + GROUND_Y, W, 1)",
        "            for i in range(3 if self.lives > 3 else self.lives):",
        "                o.fill_rect(x0 + W - 3 - i * 4, y0, 3, 2, 1)",
        "            for b in range(NBUNK):",
        "                o.blit(self.bfb[b], x0 + BUNK_X[b], y0 + BUNK_Y, 0)",
        "            for r in range(ROWS):",
        "                row = self.al[r]",
        "                spr = _SPR[_ROW_TYPE[r]][self.frame]",
        "                ay = y0 + self.fy + r * PITCH_Y",
        "                for c in range(COLS):",
        "                    if row[c]:",
        "                        o.blit(spr, x0 + self.fx + c * PITCH_X, ay, 0)",
        "            if self.ufo:",
        "                o.blit(_UFO, x0 + self.ufo_x, y0 + UFO_Y, 0)",
        "            if (not hit_pause) or (self.now // 120) & 1:",
        "                o.blit(_PLAYER, x0 + self.px, y0 + PLAY_Y, 0)",
        "            if self.b_act:",
        "                o.vline(x0 + self.bx, y0 + self.by, 3, 1)",
        "            for bm in self.bombs:",
        "                if bm[0]:",
        "                    o.vline(x0 + bm[1], y0 + bm[2], 2, 1)",
        "            if time.ticks_diff(self.pop_until, self.now) > 0:",
        "                o.text(self.pop_txt, x0 + self.pop_x, y0 + 6, 1)",
        "            o.show()",
        "",
        "        def _screen(self, lines):",
        "            \"\"\"lines = list of (text, y) inside the 72x40 window; 8x8 font,",
        "            9 chars max per line, centred.\"\"\"",
        "            o = self.o",
        "            o.fill(0)",
        "            for txt, y in lines:",
        "                o.text(txt, self.x0 + (W - 8 * len(txt)) // 2, self.y0 + y, 1)",
        "            o.show()",
        "",
        "        # ---------------- top-level state machine ----------------",
        "        def run(self):",
        "            while True:                       # forever; RST exits",
        "                # title",
        "                self.clear_events()",
        "                blink = True",
        "                last = 0",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    if self.take_release():",
        "                        break",
        "                    if time.ticks_diff(self.now, last) >= 400:",
        "                        last = self.now",
        "                        blink = not blink",
        "                        self._screen([(\"INVADERS\", 2),",
        "                                      (\"HI %d\" % self.hi, 16),",
        "                                      (\"TAP\", 30) if blink else (\"\", 30)])",
        "                    time.sleep_ms(15)",
        "",
        "                self.score = 0",
        "                self.lives = 3",
        "                wave = 1",
        "                playing = True",
        "                while playing:",
        "                    # wave splash",
        "                    self.init_wave(wave)",
        "                    self._screen([(\"WAVE %d\" % wave, 8),",
        "                                  (\"%d\" % self.score, 24)])",
        "                    t0 = self.now",
        "                    while time.ticks_diff(self.now, t0) < WAVE_MSG_MS:",
        "                        self.now = time.ticks_ms()",
        "                        self._poll()",
        "                        self._led_set()",
        "                        time.sleep_ms(15)",
        "                    self.clear_events()",
        "                    # re-anchor timers after the splash",
        "                    self.init_wave(wave)",
        "",
        "                    # play",
        "                    lf = 0",
        "                    while True:",
        "                        self.now = time.ticks_ms()",
        "                        self._poll()",
        "                        self._led_set()",
        "                        ev = self.update_play()",
        "                        if ev == 1:               # wave cleared",
        "                            wave += 1",
        "                            break",
        "                        if ev == 3:               # invaded",
        "                            playing = False",
        "                            break",
        "                        if ev == 2:               # life lost",
        "                            self.blink(350)",
        "                            self.lives -= 1",
        "                            for bm in self.bombs:",
        "                                bm[0] = False",
        "                            self.b_act = False",
        "                            if self.lives == 0:",
        "                                playing = False",
        "                                break",
        "                            self.px = (W - PLAY_W) // 2",
        "                            t0 = self.now",
        "                            while time.ticks_diff(self.now, t0) < HIT_PAUSE_MS:",
        "                                self.now = time.ticks_ms()",
        "                                self._poll()",
        "                                self._led_set()",
        "                                if time.ticks_diff(self.now, lf) >= FRAME_MS:",
        "                                    lf = self.now",
        "                                    self.draw_play(True)",
        "                                time.sleep_ms(5)",
        "                            self.clear_events()",
        "                            t = self.now",
        "                            self.next_pmove = t",
        "                            self.next_step = time.ticks_add(t, self.step_ms())",
        "                            self.next_bmove = t",
        "                            self.next_bdrop = time.ticks_add(t, 800)",
        "                            self.fire_at = time.ticks_add(t, 300)",
        "                            continue",
        "                        if time.ticks_diff(self.now, lf) >= FRAME_MS:",
        "                            lf = self.now",
        "                            self.draw_play(False)",
        "                        time.sleep_ms(5)",
        "",
        "                # game over",
        "                if self.score > self.hi:",
        "                    self.hi = self.score",
        "                    _save_hi(self.hi)",
        "                self.clear_events()",
        "                cleared = False",
        "                cleared_at = 0",
        "                last = 0",
        "                alt = False",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    if (not cleared) and self.held() >= _HI_CLEAR_MS:",
        "                        self.hi = 0",
        "                        _save_hi(0)",
        "                        cleared = True",
        "                        cleared_at = self.now",
        "                        self.blink(200)",
        "                    rel = self.take_release()",
        "                    if 0 < rel < 600:",
        "                        break",
        "                    if time.ticks_diff(self.now, last) >= 600:",
        "                        last = self.now",
        "                        alt = not alt",
        "                        hi_line = \"HI RESET\" if (cleared and time.ticks_diff(",
        "                            self.now, cleared_at) < 1200) else \"HI %d\" % self.hi",
        "                        self._screen([(\"GAME OVER\", 0),",
        "                                      (\"SC %d\" % self.score, 12),",
        "                                      (hi_line, 22),",
        "                                      (\"TAP\" if alt else \"HOLD=CLR\", 32)])",
        "                    time.sleep_ms(15)",
        "",
        "",
        "    Game(oled, btn, x0, y0, led).run()",
        ""
    ].join('\n');

    Blockly.Blocks['play_invaders_standalone'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Play Invaders (standalone)');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/invaders.jpg", 55, 55, "*"));
            this.appendDummyInput()
                // 5/6, not 0/0: this is the OLED's actual bus on every
                // classroom robot. 0/0 crashes the whole board - see the
                // ValueError guard in the generator below.
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            // No next connector: the game never returns.
            this.setTooltip('Start Invaders. The whole game is inside this block, so nothing needs uploading first. Tap BOOT to reverse the cannon. This block never finishes - press RST on the board to get back to your program.');
        }
    };

    Blockly.Python['play_invaders_standalone'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        // definitions_ so the game lands above the program body rather than
        // in the middle of it.
        Blockly.Python.definitions_['import_invaders_sa'] = 'from machine import Pin, I2C\nimport ssd1306\nimport framebuf';
        Blockly.Python.definitions_['invaders_standalone_src'] = INVADERS_SRC;

        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.shutdown()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Play Invaders (standalone): SDA and SCL cannot be the same pin")\n' +
                '_invaders_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_invaders_oled = ssd1306.SSD1306_I2C(128, 64, _invaders_i2c)\n' +
                '_invaders_led = Pin(8, Pin.OUT)\n' +
                '_invaders_led.value(1)\n' +
                '_play_invaders(_invaders_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=_invaders_led)\n';
    };

    /* Second entry in the Games category, same shape as Invaders: one
       button (tap BOOT to turn right), snake.run() never returns, matching
       firmware/snake.py. SDA/SCL default to 5/6 (the OLED's real wiring on
       every classroom robot) and the generator guards SDA == SCL, for the
       same reason as Invaders - see the comment on that block. */
    Blockly.Blocks['play_snake'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Play Snake');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/snake.jpg", 55, 55, "*"));
            this.appendDummyInput()
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            this.setTooltip('Start Snake on the OLED. Tap BOOT to turn right. This block never finishes - press RST on the board to get back to your program. Anything after it will not run.');
        }
    };

    Blockly.Python['play_snake'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        Blockly.Python.definitions_['import_snake'] =
            'import snake\n' +
            'from machine import Pin, I2C\n' +
            'import ssd1306';

        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.os_timer(False)\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Play Snake: SDA and SCL cannot be the same pin")\n' +
                '_snk_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_snk_oled = ssd1306.SSD1306_I2C(128, 64, _snk_i2c)\n' +
                'snake.run(_snk_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=Pin(8, Pin.OUT))\n';
    };

    /* Standalone twin of Snake above, same reasoning as standalone Invaders:
       the whole game embedded as Python source text, runs on a board with
       nothing on it but ssd1306.py. */
    var SNAKE_SRC = [
        "def _play_snake(oled, btn, x0=28, y0=24, led=None):",
        "    # Whole game nested here, so it creates exactly one global.",
        "    import time",
        "    import random",
        "",
        "    VISIBLE_W = 72",
        "    VISIBLE_H = 40",
        "    GRID = 4",
        "",
        "    DIR_UP = (0, -1)",
        "    DIR_RIGHT = (1, 0)",
        "    DIR_DOWN = (0, 1)",
        "    DIR_LEFT = (-1, 0)",
        "    DIR_SEQUENCE = (DIR_UP, DIR_RIGHT, DIR_DOWN, DIR_LEFT)",
        "",
        "    # Top 8 pixels are reserved for the score.",
        "    PLAY_Y = 8",
        "    COLS = VISIBLE_W // GRID           # 18",
        "    ROWS = (VISIBLE_H - PLAY_Y) // GRID  # 8",
        "",
        "    START_SPEED_MS = 180",
        "    MIN_SPEED_MS = 70",
        "    SPEED_STEP_MS = 5",
        "",
        "    HI_FILE = \"snake_hi.txt\"",
        "    HOLD_CLEAR_MS = 2000       # game-over hold to clear the high score",
        "",
        "",
        "    def _load_hi():",
        "        try:",
        "            with open(HI_FILE) as f:",
        "                return int(f.read())",
        "        except (OSError, ValueError):",
        "            return 0",
        "",
        "",
        "    def _save_hi(v):",
        "        try:",
        "            with open(HI_FILE, \"w\") as f:",
        "                f.write(str(v))",
        "        except OSError:",
        "            pass",
        "",
        "",
        "    def _spawn_food(snake):",
        "        \"\"\"Pick an empty cell inside the play area.\"\"\"",
        "        free = []",
        "        for y in range(ROWS):",
        "            for x in range(COLS):",
        "                if [x, y] not in snake:",
        "                    free.append([x, y])",
        "",
        "        if not free:",
        "            return None",
        "",
        "        return free[random.randrange(len(free))]",
        "",
        "",
        "    def _wait_for_tap(button):",
        "        \"\"\"Wait for one clean press and release.\"\"\"",
        "        while button.value() == 1:",
        "            time.sleep_ms(20)",
        "",
        "        while button.value() == 0:",
        "            time.sleep_ms(20)",
        "",
        "        # tiny debounce delay",
        "        time.sleep_ms(80)",
        "",
        "",
        "    def _show_game_over(oled, button, x0, y0, score, hi):",
        "        \"\"\"Show the result and wait. Returns the (possibly cleared) high score.",
        "",
        "        Holding the button for two seconds wipes the saved score. Same gesture",
        "        as invaders.py, so a student who learns it in one game knows it in the",
        "        other.",
        "        \"\"\"",
        "        beat = score > hi",
        "        if beat:",
        "            hi = score",
        "            _save_hi(hi)",
        "",
        "        oled.fill(0)",
        "        oled.text(\"NEW BEST!\" if beat else \"GAME OVER\", x0, y0)",
        "        oled.text(\"SCORE \" + str(score), x0, y0 + 8)",
        "        oled.text(\"BEST  \" + str(hi), x0, y0 + 16)",
        "        oled.text(\"TAP RETRY\", x0, y0 + 24)",
        "        oled.show()",
        "",
        "        time.sleep_ms(400)",
        "",
        "        # Only a SHORT tap restarts, matching invaders.py and defender.py. If any",
        "        # release restarted, the two-second hold that clears the score would",
        "        # restart on release too and the confirmation would vanish unread.",
        "        cleared = False",
        "        while True:",
        "            while button.value() == 1:",
        "                time.sleep_ms(20)",
        "",
        "            held_from = time.ticks_ms()",
        "            while button.value() == 0:",
        "                if (not cleared) and time.ticks_diff(",
        "                        time.ticks_ms(), held_from) > HOLD_CLEAR_MS:",
        "                    hi = 0",
        "                    _save_hi(0)",
        "                    cleared = True",
        "                    oled.fill(0)",
        "                    oled.text(\"HI SCORE\", x0, y0 + 8)",
        "                    oled.text(\"CLEARED\", x0, y0 + 20)",
        "                    oled.show()",
        "                time.sleep_ms(20)",
        "",
        "            held = time.ticks_diff(time.ticks_ms(), held_from)",
        "            time.sleep_ms(80)          # debounce",
        "            if 0 < held < 600:",
        "                return hi",
        "            # A long press was the clear gesture, not a restart. Redraw and wait",
        "            # for the tap that actually restarts.",
        "            oled.fill(0)",
        "            oled.text(\"NEW BEST!\" if beat else \"GAME OVER\", x0, y0)",
        "            oled.text(\"SCORE \" + str(score), x0, y0 + 8)",
        "            oled.text(\"BEST  \" + str(hi), x0, y0 + 16)",
        "            oled.text(\"TAP RETRY\", x0, y0 + 24)",
        "            oled.show()",
        "",
        "",
        "    def _draw(oled, x0, y0, snake, food, score, hi=0):",
        "        oled.fill(0)",
        "",
        "        # Score row + divider. The best score sits right-aligned so there is",
        "        # always something to beat on screen.",
        "        oled.text(str(score), x0, y0)",
        "        if hi:",
        "            s = \"H\" + str(hi)",
        "            oled.text(s, x0 + VISIBLE_W - 8 * len(s), y0)",
        "        oled.hline(x0, y0 + 7, VISIBLE_W, 1)",
        "",
        "        # Food",
        "        if food is not None:",
        "            fx = x0 + food[0] * GRID",
        "            fy = y0 + PLAY_Y + food[1] * GRID",
        "            oled.fill_rect(fx, fy, GRID - 1, GRID - 1, 1)",
        "",
        "        # Snake",
        "        for i, segment in enumerate(snake):",
        "            sx = x0 + segment[0] * GRID",
        "            sy = y0 + PLAY_Y + segment[1] * GRID",
        "",
        "            # Head is solid 4x4; body is 3x3 so direction is easier to see.",
        "            if i == 0:",
        "                oled.fill_rect(sx, sy, GRID, GRID, 1)",
        "            else:",
        "                oled.fill_rect(sx, sy, GRID - 1, GRID - 1, 1)",
        "",
        "        oled.show()",
        "",
        "",
        "    def _game(oled, button, x0=28, y0=24, led=None):",
        "        \"\"\"Run Snake using the robot's existing OLED and BOOT button.",
        "",
        "        The caller should stop robot Timer 0 before entering this function.",
        "        This function deliberately never returns during normal play.",
        "        Press the board RESET button to leave the game.",
        "        \"\"\"",
        "",
        "        hi = _load_hi()",
        "",
        "        while True:",
        "            # Start roughly in the middle of the 18x8 play field, moving right.",
        "            snake = [[8, 4], [7, 4], [6, 4]]",
        "            dir_idx = 1",
        "            food = _spawn_food(snake)",
        "            score = 0",
        "            speed_ms = START_SPEED_MS",
        "            button_was_down = False",
        "",
        "            _draw(oled, x0, y0, snake, food, score, hi)",
        "",
        "            while True:",
        "                # Poll repeatedly during the movement delay so short taps",
        "                # register. A boolean rather than a counter, deliberately: two",
        "                # taps inside one step would otherwise turn 180 degrees straight",
        "                # into the snake's own neck, which reads as the game cheating.",
        "                turned_this_step = False",
        "                slices = 12",
        "                slice_ms = max(1, speed_ms // slices)",
        "",
        "                for _ in range(slices):",
        "                    down = (button.value() == 0)",
        "",
        "                    if down and not button_was_down:",
        "                        turned_this_step = True",
        "",
        "                    button_was_down = down",
        "                    time.sleep_ms(slice_ms)",
        "",
        "                if turned_this_step:",
        "                    dir_idx = (dir_idx + 1) % 4",
        "",
        "                dx, dy = DIR_SEQUENCE[dir_idx]",
        "                new_head = [",
        "                    snake[0][0] + dx,",
        "                    snake[0][1] + dy,",
        "                ]",
        "",
        "                # Wall collision",
        "                if (",
        "                    new_head[0] < 0",
        "                    or new_head[0] >= COLS",
        "                    or new_head[1] < 0",
        "                    or new_head[1] >= ROWS",
        "                ):",
        "                    break",
        "",
        "                eating = (food is not None and new_head == food)",
        "",
        "                # Moving into the current tail cell is legal when the tail is",
        "                # about to move away; all other body collisions end the round.",
        "                body_to_check = snake if eating else snake[:-1]",
        "                if new_head in body_to_check:",
        "                    break",
        "",
        "                snake.insert(0, new_head)",
        "",
        "                if eating:",
        "                    score += 1",
        "                    food = _spawn_food(snake)",
        "",
        "                    # Full board = win; show it through the normal game-over screen.",
        "                    if food is None:",
        "                        _draw(oled, x0, y0, snake, food, score, hi)",
        "                        break",
        "",
        "                    speed_ms = max(",
        "                        MIN_SPEED_MS,",
        "                        START_SPEED_MS - score * SPEED_STEP_MS",
        "                    )",
        "",
        "                    # Tiny LED flash on food if an LED object was supplied.",
        "                    if led is not None:",
        "                        try:",
        "                            led.value(0)  # onboard LED is inverted on this board",
        "                            time.sleep_ms(35)",
        "                            led.value(1)",
        "                        except Exception:",
        "                            pass",
        "                else:",
        "                    snake.pop()",
        "",
        "                _draw(oled, x0, y0, snake, food, score, hi)",
        "",
        "            hi = _show_game_over(oled, button, x0, y0, score, hi)",
        "",
        "    _game(oled, btn, x0, y0, led)",
        ""
    ].join('\n');

    Blockly.Blocks['play_snake_standalone'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Play Snake (standalone)');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/snake.jpg", 55, 55, "*"));
            this.appendDummyInput()
                // 5/6, not 0/0: this is the OLED's actual bus on every
                // classroom robot. 0/0 crashes the whole board - see the
                // ValueError guard in the generator below.
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            // No next connector: the game never returns.
            this.setTooltip('Start Snake. The whole game is inside this block, so nothing needs uploading first. Tap BOOT to turn right. This block never finishes - press RST on the board to get back to your program.');
        }
    };

    Blockly.Python['play_snake_standalone'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        // definitions_ so the game lands above the program body rather than
        // in the middle of it.
        Blockly.Python.definitions_['import_snake_sa'] = 'from machine import Pin, I2C\nimport ssd1306';
        Blockly.Python.definitions_['snake_standalone_src'] = SNAKE_SRC;

        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.shutdown()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Play Snake (standalone): SDA and SCL cannot be the same pin")\n' +
                '_snake_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_snake_oled = ssd1306.SSD1306_I2C(128, 64, _snake_i2c)\n' +
                '_snake_led = Pin(8, Pin.OUT)\n' +
                '_snake_led.value(1)\n' +
                '_play_snake(_snake_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=_snake_led)\n';
    };

    /* Third entry: Defender, file-based - needs firmware/defender.py on the
       board, same shape as Invaders/Snake (defender.py's button handling is
       byte-identical to invaders.py per its own header comment). */
    Blockly.Blocks['play_defender'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Play Defender');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/defender.jpg", 55, 55, "*"));
            this.appendDummyInput()
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            this.setTooltip('Start Defender on the OLED. The ship fires by itself; tap BOOT to change altitude. This block never finishes - press RST on the board to get back to your program. Anything after it will not run.');
        }
    };

    Blockly.Python['play_defender'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        Blockly.Python.definitions_['import_defender'] =
            'import defender\n' +
            'from machine import Pin, I2C\n' +
            'import ssd1306';

        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.os_timer(False)\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Play Defender: SDA and SCL cannot be the same pin")\n' +
                '_def_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_def_oled = ssd1306.SSD1306_I2C(128, 64, _def_i2c)\n' +
                'defender.run(_def_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=Pin(8, Pin.OUT))\n';
    };


    /* Fourth entry: Defender (standalone), and the standalone Invaders/Snake
       above follow the exact same shape. SELF-CONTAINED - the whole game is
       embedded below as Python source text, so this runs on a board with
       nothing uploaded but ssd1306.py. The trade against the file-based
       block above: it can't be opened or edited in BIPES' code editor
       (there is no file), it sends several KB over serial on every run
       instead of three lines, and it compiles hundreds of lines on the
       board each time instead of importing a pre-compiled module. Keep
       both - they serve different situations (a board with defender.py
       already on it vs. one fresh off the flasher).

       robot.shutdown() rather than robot.os_timer(False) here (and now on
       all three standalone blocks): shutdown() also stops the motors and
       the servo, which matters more for a standalone game that could be
       dropped into a program mid-drive with nothing uploaded to check
       against - os_stop(), which an earlier draft of this block called,
       never existed. */
    var DEFENDER_SRC = [
        "def _play_defender(oled, btn, x0=28, y0=24, led=None):",
        "    # The whole game nested in one function, so nothing lands in the global",
        "    # namespace. A student program with its own W, H, run or Game will not",
        "    # collide with the game's.",
        "    import time",
        "    import random",
        "",
        "    # ---------------- playfield geometry (72x40 window) ----------------",
        "    W = 72",
        "    H = 40",
        "    BANDS = 3",
        "    NENEMY = 6",
        "    NSHOT = 6",
        "    SHIP_X = 3",
        "    SPAWN_MS = 700",
        "    FIRE_MS = 350",
        "    ENEMY_SPEED = 18.0",
        "    SHOT_SPEED = 40.0",
        "",
        "",
        "    def _band_y(band):",
        "        return 8 + band * 10",
        "",
        "    # ---------------- shared tuning ----------------",
        "    FRAME_MS = 40          # ~25 fps target; oled.show() is the real throttle",
        "    MAX_STEP_MS = 50       # cap one physics step so a slow frame can't tunnel",
        "    HIT_PAUSE_MS = 900",
        "    WAVE_MSG_MS = 1400",
        "    HI_FILE = \"defender_hi.txt\"",
        "",
        "    # game-over hold to clear the high score",
        "    _HI_CLEAR_MS = 2000",
        "",
        "    # tiny 3x5 digits for the in-game score (the 8x8 font is too big)",
        "    _DIG = (",
        "        (7, 5, 5, 5, 7), (2, 6, 2, 2, 7), (7, 1, 7, 4, 7), (7, 1, 7, 1, 7),",
        "        (5, 5, 7, 1, 1), (7, 4, 7, 1, 7), (7, 4, 7, 5, 7), (7, 1, 1, 1, 1),",
        "        (7, 5, 7, 5, 7), (7, 5, 7, 1, 7),",
        "    )",
        "",
        "",
        "    def _num(o, x, y, n, xor=False):",
        "        \"\"\"Draw integer n with 3x5 digits, top-left at (x, y).\"\"\"",
        "        for ch in str(n):",
        "            rows = _DIG[ord(ch) - 48]",
        "            for r in range(5):",
        "                bits = rows[r]",
        "                for i in range(3):",
        "                    if bits & (4 >> i):",
        "                        px = x + i",
        "                        py = y + r",
        "                        o.pixel(px, py, (0 if o.pixel(px, py) else 1) if xor else 1)",
        "            x += 4",
        "",
        "",
        "    def _load_hi():",
        "        try:",
        "            with open(HI_FILE) as f:",
        "                return int(f.read())",
        "        except (OSError, ValueError):",
        "            return 0",
        "",
        "",
        "    def _save_hi(v):",
        "        try:",
        "            with open(HI_FILE, \"w\") as f:",
        "                f.write(str(v))",
        "        except OSError:",
        "            pass",
        "",
        "",
        "    class Game:",
        "        def __init__(self, oled, btn, x0, y0, led):",
        "            self.o = oled",
        "            self.btn = btn",
        "            self.x0 = x0",
        "            self.y0 = y0",
        "            self.led = led",
        "            self.hi = _load_hi()",
        "            self.score = 0",
        "            # button state",
        "            self.down = False",
        "            self.pressed_at = 0",
        "            self.tapped = False",
        "            self.released = 0",
        "            self.led_until = 0",
        "            self.now = time.ticks_ms()",
        "            self._setup()",
        "",
        "        # ---------------- button ----------------",
        "        def _poll(self):",
        "            v = self.btn.value() == 0",
        "            if v and not self.down:",
        "                self.down = True",
        "                self.pressed_at = self.now",
        "                self.tapped = True",
        "            elif (not v) and self.down:",
        "                self.down = False",
        "                d = time.ticks_diff(self.now, self.pressed_at)",
        "                self.released = d if d > 0 else 1",
        "",
        "        def take_tap(self):",
        "            t = self.tapped",
        "            self.tapped = False",
        "            return t",
        "",
        "        def take_release(self):",
        "            v = self.released",
        "            self.released = 0",
        "            return v",
        "",
        "        def held(self):",
        "            return time.ticks_diff(self.now, self.pressed_at) if self.down else 0",
        "",
        "        def clear_events(self):",
        "            self.tapped = False",
        "            self.released = 0",
        "",
        "        def _led_set(self):",
        "            if self.led is not None:",
        "                self.led.value(0 if time.ticks_diff(self.led_until, self.now) > 0",
        "                               else 1)",
        "",
        "        def blink(self, ms):",
        "            self.led_until = time.ticks_add(self.now, ms)",
        "",
        "        # ---------------- drawing helpers ----------------",
        "        def _screen(self, lines):",
        "            \"\"\"lines = list of (text, y) inside the 72x40 window; 8x8 font,",
        "            9 chars max per line, centred.\"\"\"",
        "            o = self.o",
        "            o.fill(0)",
        "            for txt, y in lines:",
        "                o.text(txt, self.x0 + (W - 8 * len(txt)) // 2, self.y0 + y, 1)",
        "            o.show()",
        "",
        "        def _wait(self, ms):",
        "            \"\"\"Idle for ms while keeping the button and LED serviced.\"\"\"",
        "            t0 = self.now",
        "            while time.ticks_diff(self.now, t0) < ms:",
        "                self.now = time.ticks_ms()",
        "                self._poll()",
        "                self._led_set()",
        "                time.sleep_ms(15)",
        "",
        "        def _setup(self):",
        "            # [active, band, x]",
        "            self.enemies = [[False, 0, 0.0] for _ in range(NENEMY)]",
        "            self.shots = [[False, 0, 0.0] for _ in range(NSHOT)]",
        "",
        "        def reset(self):",
        "            self.score = 0",
        "            self.band = 1",
        "            self.spawn_timer = 0",
        "            self.fire_timer = 0",
        "            for e in self.enemies:",
        "                e[0] = False",
        "            for s in self.shots:",
        "                s[0] = False",
        "",
        "        def _spawn_enemy(self):",
        "            for e in self.enemies:",
        "                if not e[0]:",
        "                    e[0] = True",
        "                    e[1] = random.randint(0, BANDS - 1)",
        "                    e[2] = float(W - 5)",
        "                    return",
        "",
        "        def _fire(self):",
        "            for s in self.shots:",
        "                if not s[0]:",
        "                    s[0] = True",
        "                    s[1] = self.band",
        "                    s[2] = float(SHIP_X + 5)",
        "                    return",
        "",
        "        # ---------------- gameplay ----------------",
        "        def update(self, dt_ms):",
        "            \"\"\"Returns 0 = keep playing, 2 = game over.\"\"\"",
        "            if self.take_tap():",
        "                self.band = (self.band + 1) % BANDS",
        "            self.take_release()",
        "",
        "            self.spawn_timer += dt_ms",
        "            if self.spawn_timer >= SPAWN_MS:",
        "                self.spawn_timer = 0",
        "                self._spawn_enemy()",
        "            self.fire_timer += dt_ms",
        "            if self.fire_timer >= FIRE_MS:",
        "                self.fire_timer = 0",
        "                self._fire()",
        "",
        "            dt = dt_ms * 0.001",
        "            emove = ENEMY_SPEED * dt",
        "            smove = SHOT_SPEED * dt",
        "            for e in self.enemies:",
        "                if not e[0]:",
        "                    continue",
        "                e[2] -= emove",
        "                if e[2] <= SHIP_X + 2 and e[1] == self.band:",
        "                    return 2",
        "                elif e[2] < 0:",
        "                    e[0] = False",
        "            for s in self.shots:",
        "                if not s[0]:",
        "                    continue",
        "                s[2] += smove",
        "                if s[2] > W:",
        "                    s[0] = False",
        "            for e in self.enemies:",
        "                if not e[0]:",
        "                    continue",
        "                for s in self.shots:",
        "                    if s[0] and s[1] == e[1] and e[2] <= s[2] <= e[2] + 3:",
        "                        s[0] = False",
        "                        e[0] = False",
        "                        self.score += 1",
        "                        self.blink(60)",
        "                        break",
        "            return 0",
        "",
        "        # ---------------- drawing ----------------",
        "        def draw(self):",
        "            o = self.o",
        "            x0 = self.x0",
        "            y0 = self.y0",
        "            o.fill(0)",
        "            o.fill_rect(x0 + SHIP_X, y0 + _band_y(self.band), 4, 3, 1)",
        "            for e in self.enemies:",
        "                if e[0]:",
        "                    o.rect(x0 + int(e[2]), y0 + _band_y(e[1]), 4, 3, 1)",
        "            for s in self.shots:",
        "                if s[0]:",
        "                    o.pixel(x0 + int(s[2]), y0 + _band_y(s[1]) + 1, 1)",
        "            _num(o, x0 + 1, y0 + 1, self.score)",
        "            o.show()",
        "",
        "        # ---------------- top-level state machine ----------------",
        "        def run(self):",
        "            while True:                       # forever; RST exits",
        "                # title",
        "                self.clear_events()",
        "                blink = True",
        "                last = 0",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    if self.take_release():",
        "                        break",
        "                    if time.ticks_diff(self.now, last) >= 400:",
        "                        last = self.now",
        "                        blink = not blink",
        "                        self._screen([(\"DEFENDER\", 2),",
        "                                      (\"HI %d\" % self.hi, 16),",
        "                                      (\"TAP\", 30) if blink else (\"\", 30)])",
        "                    time.sleep_ms(15)",
        "",
        "                # play",
        "                self.now = time.ticks_ms()",
        "                self.reset()",
        "                self.clear_events()",
        "                lf = 0",
        "                last_upd = self.now",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    dt = time.ticks_diff(self.now, last_upd)",
        "                    last_upd = self.now",
        "                    if dt > MAX_STEP_MS:",
        "                        dt = MAX_STEP_MS",
        "                    if self.update(dt):",
        "                        break",
        "                    if time.ticks_diff(self.now, lf) >= FRAME_MS:",
        "                        lf = self.now",
        "                        self.draw()",
        "                    time.sleep_ms(5)",
        "                self.draw()                   # show the fatal frame briefly",
        "                self.blink(350)",
        "                self._wait(700)",
        "",
        "                # game over",
        "                if self.score > self.hi:",
        "                    self.hi = self.score",
        "                    _save_hi(self.hi)",
        "                self.clear_events()",
        "                cleared = False",
        "                cleared_at = 0",
        "                last = 0",
        "                alt = False",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    if (not cleared) and self.held() >= _HI_CLEAR_MS:",
        "                        self.hi = 0",
        "                        _save_hi(0)",
        "                        cleared = True",
        "                        cleared_at = self.now",
        "                        self.blink(200)",
        "                    rel = self.take_release()",
        "                    if 0 < rel < 600:",
        "                        break",
        "                    if time.ticks_diff(self.now, last) >= 600:",
        "                        last = self.now",
        "                        alt = not alt",
        "                        hi_line = \"HI RESET\" if (cleared and time.ticks_diff(",
        "                            self.now, cleared_at) < 1200) else \"HI %d\" % self.hi",
        "                        self._screen([(\"GAME OVER\", 0),",
        "                                      (\"SC %d\" % self.score, 12),",
        "                                      (hi_line, 22),",
        "                                      (\"TAP\" if alt else \"HOLD=CLR\", 32)])",
        "                    time.sleep_ms(15)",
        "",
        "",
        "    Game(oled, btn, x0, y0, led).run()",
        ""
    ].join('\n');

    Blockly.Blocks['play_defender_standalone'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Play Defender (standalone)');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/defender.jpg", 55, 55, "*"));
            this.appendDummyInput()
                // 5/6, not 0/0: this is the OLED's actual bus on every
                // classroom robot. 0/0 crashes the whole board - see the
                // ValueError guard in the generator below.
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            // No next connector: the game never returns.
            this.setTooltip('Start Defender. The whole game is inside this block, so nothing needs uploading first. The ship fires by itself; tap BOOT to change altitude. This block never finishes - press RST on the board to get back to your program.');
        }
    };

    Blockly.Python['play_defender_standalone'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        // definitions_ so the game lands above the program body rather than
        // in the middle of it.
        Blockly.Python.definitions_['import_defender_sa'] = 'from machine import Pin, I2C\nimport ssd1306';
        Blockly.Python.definitions_['defender_standalone_src'] = DEFENDER_SRC;

        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.shutdown()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Play Defender (standalone): SDA and SCL cannot be the same pin")\n' +
                '_defender_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_defender_oled = ssd1306.SSD1306_I2C(128, 64, _defender_i2c)\n' +
                '_defender_led = Pin(8, Pin.OUT)\n' +
                '_defender_led.value(1)\n' +
                '_play_defender(_defender_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=_defender_led)\n';
    };

    /* Frogger is standalone: the complete game is emitted into the generated
       Python program, so no frogger.py upload or provisioning change is
       required. */
    var FROGGER_SRC = [
        "def _play_frogger(oled, btn, x0=28, y0=24, led=None):",
        "    # Everything is nested so the generated program gets one global only.",
        "    import time",
        "    import random",
        "    ",
        "    # ---------------- playfield geometry (72x40 window) ----------------",
        "    W = 72",
        "    H = 40",
        "    # row -> top y. 0 home, 1-2 river, 3 median, 4-5 road, 6 start",
        "    ROW_Y = (0, 6, 12, 18, 22, 28, 34)",
        "    NROWS = 7",
        "    HOME_ROW = 0",
        "    START_ROW = 6",
        "    MEDIAN_ROW = 3",
        "    COL_W = 8",
        "    FROG_W = 6",
        "    FROG_H = 5",
        "    OBJ_H = 5",
        "    HOME_X = (8, 24, 40, 56)",
        "    HOME_W = 8",
        "    LIVES = 3",
        "    ",
        "    # overall traffic speed: 1.0 = original, 0.5 = half speed",
        "    SPEED = 0.5",
        "    ",
        "    # gesture timing",
        "    HOLD_MS = 220",
        "    DOUBLE_MS = 220",
        "    REPEAT_MS = 300",
        "    ",
        "    # lanes: (row, dir, px/s, object width, gap, is_log)",
        "    LANES = (",
        "        (1, 1, 12.0, 20, 14, True),",
        "        (2, -1, 9.0, 16, 16, True),",
        "        (4, -1, 14.0, 9, 23, False),",
        "        (5, 1, 10.0, 12, 26, False),",
        "    )",
        "    ",
        "    # hop directions",
        "    LEFT = 0",
        "    RIGHT = 1",
        "    FWD = 2",
        "    BACK = 3",
        "    ",
        "    ",
        "    def _fb(rows, w, h):",
        "        import framebuf",
        "        return framebuf.FrameBuffer(bytearray(rows), w, h, framebuf.MONO_HLSB)",
        "    ",
        "    ",
        "    _FROG = _fb(b\"\\xB4\\xFC\\x78\\xFC\\x84\", 6, 5)   # MSB = leftmost pixel",
        "    ",
        "    ",
        "    def _frog_xor(o, x, y):",
        "        \"\"\"Draw the frog by inverting what is under it, so it shows white on",
        "        water and as a dark cut-out on a log.\"\"\"",
        "        for yy in range(FROG_H):",
        "            for xx in range(FROG_W):",
        "                if _FROG.pixel(xx, yy):",
        "                    o.pixel(x + xx, y + yy, 0 if o.pixel(x + xx, y + yy) else 1)",
        "    ",
        "    # ---------------- shared tuning ----------------",
        "    FRAME_MS = 40          # ~25 fps target; oled.show() is the real throttle",
        "    MAX_STEP_MS = 50       # cap one physics step so a slow frame can't tunnel",
        "    HIT_PAUSE_MS = 900",
        "    WAVE_MSG_MS = 1400",
        "    HI_FILE = \"frogger_hi.txt\"",
        "    ",
        "    # game-over hold to clear the high score",
        "    _HI_CLEAR_MS = 2000",
        "    ",
        "    # tiny 3x5 digits for the in-game score (the 8x8 font is too big)",
        "    _DIG = (",
        "        (7, 5, 5, 5, 7), (2, 6, 2, 2, 7), (7, 1, 7, 4, 7), (7, 1, 7, 1, 7),",
        "        (5, 5, 7, 1, 1), (7, 4, 7, 1, 7), (7, 4, 7, 5, 7), (7, 1, 1, 1, 1),",
        "        (7, 5, 7, 5, 7), (7, 5, 7, 1, 7),",
        "    )",
        "    ",
        "    ",
        "    def _num(o, x, y, n, xor=False):",
        "        \"\"\"Draw integer n with 3x5 digits, top-left at (x, y).\"\"\"",
        "        for ch in str(n):",
        "            rows = _DIG[ord(ch) - 48]",
        "            for r in range(5):",
        "                bits = rows[r]",
        "                for i in range(3):",
        "                    if bits & (4 >> i):",
        "                        px = x + i",
        "                        py = y + r",
        "                        o.pixel(px, py, (0 if o.pixel(px, py) else 1) if xor else 1)",
        "            x += 4",
        "    ",
        "    ",
        "    def _load_hi():",
        "        try:",
        "            with open(HI_FILE) as f:",
        "                return int(f.read())",
        "        except (OSError, ValueError):",
        "            return 0",
        "    ",
        "    ",
        "    def _save_hi(v):",
        "        try:",
        "            with open(HI_FILE, \"w\") as f:",
        "                f.write(str(v))",
        "        except OSError:",
        "            pass",
        "    ",
        "    ",
        "    class Game:",
        "        def __init__(self, oled, btn, x0, y0, led):",
        "            self.o = oled",
        "            self.btn = btn",
        "            self.x0 = x0",
        "            self.y0 = y0",
        "            self.led = led",
        "            self.hi = _load_hi()",
        "            self.score = 0",
        "            # button state",
        "            self.down = False",
        "            self.pressed_at = 0",
        "            self.tapped = False",
        "            self.released = 0",
        "            self.led_until = 0",
        "            self.now = time.ticks_ms()",
        "            self._setup()",
        "    ",
        "        # ---------------- button ----------------",
        "        def _poll(self):",
        "            v = self.btn.value() == 0",
        "            if v and not self.down:",
        "                self.down = True",
        "                self.pressed_at = self.now",
        "                self.tapped = True",
        "            elif (not v) and self.down:",
        "                self.down = False",
        "                d = time.ticks_diff(self.now, self.pressed_at)",
        "                self.released = d if d > 0 else 1",
        "    ",
        "        def take_tap(self):",
        "            t = self.tapped",
        "            self.tapped = False",
        "            return t",
        "    ",
        "        def take_release(self):",
        "            v = self.released",
        "            self.released = 0",
        "            return v",
        "    ",
        "        def held(self):",
        "            return time.ticks_diff(self.now, self.pressed_at) if self.down else 0",
        "    ",
        "        def clear_events(self):",
        "            self.tapped = False",
        "            self.released = 0",
        "    ",
        "        def _led_set(self):",
        "            if self.led is not None:",
        "                self.led.value(0 if time.ticks_diff(self.led_until, self.now) > 0",
        "                               else 1)",
        "    ",
        "        def blink(self, ms):",
        "            self.led_until = time.ticks_add(self.now, ms)",
        "    ",
        "        # ---------------- drawing helpers ----------------",
        "        def _screen(self, lines):",
        "            \"\"\"lines = list of (text, y) inside the 72x40 window; 8x8 font,",
        "            9 chars max per line, centred.\"\"\"",
        "            o = self.o",
        "            o.fill(0)",
        "            for txt, y in lines:",
        "                o.text(txt, self.x0 + (W - 8 * len(txt)) // 2, self.y0 + y, 1)",
        "            o.show()",
        "    ",
        "        def _wait(self, ms):",
        "            \"\"\"Idle for ms while keeping the button and LED serviced.\"\"\"",
        "            t0 = self.now",
        "            while time.ticks_diff(self.now, t0) < ms:",
        "                self.now = time.ticks_ms()",
        "                self._poll()",
        "                self._led_set()",
        "                time.sleep_ms(15)",
        "    ",
        "        def _setup(self):",
        "            self.off = [0.0] * len(LANES)    # scroll offset per lane",
        "            self.homes = bytearray(len(HOME_X))",
        "    ",
        "        def reset(self):",
        "            self.score = 0",
        "            self.lives = LIVES",
        "            self.level = 1",
        "            self.pause_until = self.now",
        "            self.msg = \"\"",
        "            self.dying = False",
        "            for i in range(len(HOME_X)):",
        "                self.homes[i] = 0",
        "            for i in range(len(LANES)):",
        "                self.off[i] = random.randint(0, LANES[i][3] + LANES[i][4] - 1) * 1.0",
        "            self._reset_frog()",
        "    ",
        "        def _reset_frog(self):",
        "            self.fx = float((W - FROG_W) // 2)",
        "            self.row = START_ROW",
        "            self.best_row = START_ROW",
        "            self.gst = 0",
        "            self.gt0 = self.now",
        "            self.hold_dir = FWD",
        "            self.clear_events()",
        "    ",
        "        def _speed_mul(self):",
        "            return SPEED * (1.0 + (self.level - 1) * 0.15)",
        "    ",
        "        # ---------------- one-button gesture decoder ----------------",
        "        def _gesture(self):",
        "            \"\"\"Returns a hop direction or None. States: 0 idle, 1 first press",
        "            down, 2 released (waiting for a possible second press), 3 second",
        "            press down, 4 holding (repeat).\"\"\"",
        "            now = self.now",
        "            tap = self.take_tap()",
        "            rel = self.take_release()",
        "            st = self.gst",
        "            ev = None",
        "            if st == 0:",
        "                if tap:",
        "                    self.gst = 1",
        "                    self.gt0 = now",
        "            elif st == 1:",
        "                if rel:",
        "                    self.gst = 2",
        "                    self.gt0 = now",
        "                elif time.ticks_diff(now, self.gt0) >= HOLD_MS:",
        "                    ev = FWD",
        "                    self.hold_dir = FWD",
        "                    self.gst = 4",
        "                    self.gt0 = now",
        "            elif st == 2:",
        "                if tap:",
        "                    self.gst = 3",
        "                    self.gt0 = now",
        "                elif time.ticks_diff(now, self.gt0) >= DOUBLE_MS:",
        "                    ev = LEFT",
        "                    self.gst = 0",
        "            elif st == 3:",
        "                if rel:",
        "                    ev = RIGHT",
        "                    self.gst = 0",
        "                elif time.ticks_diff(now, self.gt0) >= HOLD_MS:",
        "                    ev = BACK",
        "                    self.hold_dir = BACK",
        "                    self.gst = 4",
        "                    self.gt0 = now",
        "            else:  # 4",
        "                if not self.down:",
        "                    self.gst = 0",
        "                elif time.ticks_diff(now, self.gt0) >= REPEAT_MS:",
        "                    ev = self.hold_dir",
        "                    self.gt0 = now",
        "            return ev",
        "    ",
        "        # ---------------- lanes ----------------",
        "        def _on_object(self, lane, log):",
        "            \"\"\"log=True: is the frog's centre on a log? log=False: does any car",
        "            overlap the frog?\"\"\"",
        "            row, d, spd, w, gap, is_log = LANES[lane]",
        "            period = w + gap",
        "            x = self.off[lane] - period",
        "            fl = self.fx",
        "            fr = fl + FROG_W - 1",
        "            fc = fl + 3.0",
        "            while x < W:",
        "                if log:",
        "                    if x <= fc <= x + w - 1:",
        "                        return True",
        "                elif x <= fr and x + w - 1 >= fl:",
        "                    return True",
        "                x += period",
        "            return False",
        "    ",
        "        # ---------------- gameplay ----------------",
        "        def _die(self):",
        "            self.lives -= 1",
        "            self.blink(350)",
        "            if self.lives == 0:",
        "                return 2",
        "            self.dying = True",
        "            self.pause_until = time.ticks_add(self.now, HIT_PAUSE_MS)",
        "            return 0",
        "    ",
        "        def update(self, dt_ms):",
        "            \"\"\"Returns 0 = keep playing, 2 = game over.\"\"\"",
        "            now = self.now",
        "            if time.ticks_diff(self.pause_until, now) > 0:",
        "                self.clear_events()",
        "                return 0",
        "            if self.dying:",
        "                self.dying = False",
        "                self._reset_frog()",
        "            self.msg = \"\"",
        "            dt = dt_ms * 0.001",
        "    ",
        "            # scroll the lanes",
        "            mul = self._speed_mul()",
        "            for i in range(len(LANES)):",
        "                row, d, spd, w, gap, is_log = LANES[i]",
        "                period = w + gap",
        "                o = self.off[i] + d * spd * mul * dt",
        "                self.off[i] = o % period",
        "                if is_log and self.row == row:",
        "                    self.fx += d * spd * mul * dt",
        "    ",
        "            # hop",
        "            hop = self._gesture()",
        "            if hop is not None:",
        "                self.blink(30)",
        "                if hop == LEFT:",
        "                    self.fx -= COL_W",
        "                elif hop == RIGHT:",
        "                    self.fx += COL_W",
        "                elif hop == FWD:",
        "                    if self.row > HOME_ROW:",
        "                        self.row -= 1",
        "                        if self.row < self.best_row:",
        "                            self.best_row = self.row",
        "                            self.score += 10",
        "                elif hop == BACK:",
        "                    if self.row < START_ROW:",
        "                        self.row += 1",
        "                if self.fx < 0:",
        "                    self.fx = 0.0",
        "                elif self.fx > W - FROG_W:",
        "                    self.fx = float(W - FROG_W)",
        "    ",
        "            # reached the home bank?",
        "            if self.row == HOME_ROW:",
        "                fc = self.fx + 3.0",
        "                for i in range(len(HOME_X)):",
        "                    hx = HOME_X[i]",
        "                    if hx <= fc <= hx + HOME_W - 1 and not self.homes[i]:",
        "                        self.homes[i] = 1",
        "                        self.score += 50",
        "                        self.blink(150)",
        "                        if all(self.homes):",
        "                            self.score += 100",
        "                            self.level += 1",
        "                            for j in range(len(HOME_X)):",
        "                                self.homes[j] = 0",
        "                            self.msg = \"LEVEL %d\" % self.level",
        "                            self.pause_until = time.ticks_add(now, WAVE_MSG_MS)",
        "                        self._reset_frog()",
        "                        return 0",
        "                return self._die()          # missed the slot / slot taken",
        "    ",
        "            # lane hazards",
        "            for i in range(len(LANES)):",
        "                row, d, spd, w, gap, is_log = LANES[i]",
        "                if row != self.row:",
        "                    continue",
        "                if is_log:",
        "                    if not self._on_object(i, True):",
        "                        return self._die()  # in the water",
        "                    if self.fx < -1 or self.fx > W - FROG_W + 1:",
        "                        return self._die()  # carried off screen",
        "                elif self._on_object(i, False):",
        "                    return self._die()      # run over",
        "            return 0",
        "    ",
        "        # ---------------- drawing ----------------",
        "        def draw(self):",
        "            o = self.o",
        "            x0 = self.x0",
        "            y0 = self.y0",
        "            o.fill(0)",
        "            # home bank with slots",
        "            o.fill_rect(x0, y0, W, OBJ_H, 1)",
        "            for i in range(len(HOME_X)):",
        "                o.fill_rect(x0 + HOME_X[i], y0, HOME_W, OBJ_H, 0)",
        "                if self.homes[i]:",
        "                    o.blit(_FROG, x0 + HOME_X[i] + 1, y0, 0)",
        "            # lanes",
        "            for i in range(len(LANES)):",
        "                row, d, spd, w, gap, is_log = LANES[i]",
        "                period = w + gap",
        "                y = y0 + ROW_Y[row]",
        "                x = int(self.off[i]) - period",
        "                while x < W:",
        "                    if is_log:",
        "                        o.fill_rect(x0 + x, y, w, OBJ_H, 1)",
        "                    else:",
        "                        o.rect(x0 + x, y, w, OBJ_H, 1)",
        "                        o.hline(x0 + x + 2, y + 2, w - 4, 1)",
        "                    x += period",
        "            # median / start bank",
        "            my = y0 + ROW_Y[MEDIAN_ROW]",
        "            for x in range(0, W, 2):",
        "                o.pixel(x0 + x, my + 3, 1)",
        "            o.hline(x0, y0 + H - 1, W, 1)",
        "            # frog (flashes while dying)",
        "            if (not self.dying) or (self.now // 120) & 1:",
        "                _frog_xor(o, x0 + int(self.fx), y0 + ROW_Y[self.row])",
        "            # score, lives",
        "            _num(o, x0 + 1, my - 1, self.score, True)",
        "            for i in range(3 if self.lives > 3 else self.lives):",
        "                o.fill_rect(x0 + W - 3 - i * 4, my + 1, 3, 2, 1)",
        "            if self.msg:",
        "                o.fill_rect(x0 + 4, y0 + 15, W - 8, 10, 0)",
        "                o.text(self.msg, x0 + (W - 8 * len(self.msg)) // 2, y0 + 16, 1)",
        "            o.show()",
        "    ",
        "        # ---------------- top-level state machine ----------------",
        "        def run(self):",
        "            while True:                       # forever; RST exits",
        "                # title",
        "                self.clear_events()",
        "                blink = True",
        "                last = 0",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    if self.take_release():",
        "                        break",
        "                    if time.ticks_diff(self.now, last) >= 400:",
        "                        last = self.now",
        "                        blink = not blink",
        "                        self._screen([(\"FROGGER\", 2),",
        "                                      (\"HI %d\" % self.hi, 16),",
        "                                      (\"TAP\", 30) if blink else (\"\", 30)])",
        "                    time.sleep_ms(15)",
        "    ",
        "                # play",
        "                self.now = time.ticks_ms()",
        "                self.reset()",
        "                self.clear_events()",
        "                lf = 0",
        "                last_upd = self.now",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    dt = time.ticks_diff(self.now, last_upd)",
        "                    last_upd = self.now",
        "                    if dt > MAX_STEP_MS:",
        "                        dt = MAX_STEP_MS",
        "                    if self.update(dt):",
        "                        break",
        "                    if time.ticks_diff(self.now, lf) >= FRAME_MS:",
        "                        lf = self.now",
        "                        self.draw()",
        "                    time.sleep_ms(5)",
        "                self.draw()                   # show the fatal frame briefly",
        "                self.blink(350)",
        "                self._wait(700)",
        "    ",
        "                # game over",
        "                if self.score > self.hi:",
        "                    self.hi = self.score",
        "                    _save_hi(self.hi)",
        "                self.clear_events()",
        "                cleared = False",
        "                cleared_at = 0",
        "                last = 0",
        "                alt = False",
        "                while True:",
        "                    self.now = time.ticks_ms()",
        "                    self._poll()",
        "                    self._led_set()",
        "                    if (not cleared) and self.held() >= _HI_CLEAR_MS:",
        "                        self.hi = 0",
        "                        _save_hi(0)",
        "                        cleared = True",
        "                        cleared_at = self.now",
        "                        self.blink(200)",
        "                    rel = self.take_release()",
        "                    if 0 < rel < 600:",
        "                        break",
        "                    if time.ticks_diff(self.now, last) >= 600:",
        "                        last = self.now",
        "                        alt = not alt",
        "                        hi_line = \"HI RESET\" if (cleared and time.ticks_diff(",
        "                            self.now, cleared_at) < 1200) else \"HI %d\" % self.hi",
        "                        self._screen([(\"GAME OVER\", 0),",
        "                                      (\"SC %d\" % self.score, 12),",
        "                                      (hi_line, 22),",
        "                                      (\"TAP\" if alt else \"HOLD=CLR\", 32)])",
        "                    time.sleep_ms(15)",
        "",
        "    Game(oled, btn, x0, y0, led).run()",
        "",
    ].join('\n');

    Blockly.Blocks['play_frogger_standalone'] = {
        init: function() {
            this.setColour(290);
            this.appendDummyInput().appendField('Frogger');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/frogger.svg", 55, 55, "*"));
            this.appendDummyInput()
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            // No next connector: the game never returns.
            this.setTooltip('Start Frogger. Single-click BOOT to hop left, double-click right, hold to move forward, or double-click and hold to move back. This block never finishes - press RST to leave the game.');
        }
    };

    Blockly.Python['play_frogger_standalone'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        Blockly.Python.definitions_['import_frogger_sa'] = 'from machine import Pin, I2C\nimport ssd1306';
        Blockly.Python.definitions_['frogger_standalone_src'] = FROGGER_SRC;

        return  'try:\n' +
                '    from gyro import gyro_stop\n' +
                '    gyro_stop()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'try:\n' +
                '    import robot\n' +
                '    robot.shutdown()\n' +
                'except Exception:\n' +
                '    pass\n' +
                'if ' + sda + ' == ' + scl + ':\n' +
                '    raise ValueError("Frogger: SDA and SCL cannot be the same pin")\n' +
                '_frogger_i2c = I2C(0, scl=Pin(' + scl + '), sda=Pin(' + sda + '), freq=400000)\n' +
                '_frogger_oled = ssd1306.SSD1306_I2C(128, 64, _frogger_i2c)\n' +
                '_frogger_led = Pin(8, Pin.OUT)\n' +
                '_frogger_led.value(1)\n' +
                '_play_frogger(_frogger_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=_frogger_led)\n';
    };
});
