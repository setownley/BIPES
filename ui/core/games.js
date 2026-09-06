/*
 * Games category for the classroom fork: split out of queue.js because the
 * embedded standalone games (defender in particular, ~14KB of Python source
 * as a JS string) were about to nearly double that file's size. Everything
 * Games-related - the toolbox category injection and all four block/generator
 * pairs - lives here instead. Load order versus queue.js does not matter:
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
                    var gameBlocks = ['play_invaders', 'play_snake', 'play_defender', 'play_defender_standalone'];
                    var hasBlock = function (t) { return !!response.querySelector('block[type="' + t + '"]'); };

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

    /* Fourth entry: Defender (standalone). SELF-CONTAINED - the whole game is
       embedded below as Python source text, so this runs on a board with
       nothing uploaded but ssd1306.py. The trade against the file-based
       block above: it can't be opened or edited in BIPES' code editor
       (there is no file), it sends ~14KB over serial on every run instead of
       three lines, and it compiles ~300 lines on the board each time instead
       of importing a pre-compiled module. Keep both - they serve different
       situations (a board with defender.py already on it vs. one fresh off
       the flasher).

       The game is nested inside a single _play_defender() function, so it
       creates exactly one global and can't collide with a student's own
       variables. Logically identical to firmware/defender.py's Game class
       and helpers (diffed against it while integrating) - if one changes,
       the other should too. */
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
                .appendField('SDA').appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.setPreviousStatement(true, null);
            // No next connector: the game never returns.
            this.setTooltip('Start Defender. The whole game is inside this block, so nothing needs uploading to the board first. The ship fires by itself; tap BOOT to change altitude. This block never finishes - press RST on the board to get back to your program.');
        }
    };

    Blockly.Python['play_defender_standalone'] = function(block) {
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';

        // The game goes in definitions_ so it lands above the program body
        // rather than in the middle of it.
        Blockly.Python.definitions_['import_defender_sa'] =
            'from machine import Pin, I2C\nimport ssd1306';
        Blockly.Python.definitions_['defender_standalone_src'] = DEFENDER_SRC;

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
                '_def_led = Pin(8, Pin.OUT)\n' +
                '_def_led.value(1)\n' +
                '_play_defender(_def_oled, Pin(9, Pin.IN, Pin.PULL_UP), led=_def_led)\n';
    };

    /* The high score still persists in defender_hi.txt, created by the game
       on first play. Nothing to upload for that either. */
});
