/*
 * Queue using localstorage! 
 * Adapted from from:  https://www.javascripttutorial.net/javascript-queue/
*/

function Queue(num) {
   this.qn = num;
   var elements = JSON.parse(localStorage.getItem("queue" + this.qn));

   if (!elements) {
	   console.log("Creating a new queue");
	   var elements = [];
	   localStorage.setItem("queue" + this.qn, JSON.stringify(elements));
   }
}

Queue.prototype.enqueue = function (e) {
   var elements = JSON.parse(localStorage.getItem("queue" + this.qn));
   elements.push(e);
   localStorage.setItem("queue" + this.qn, JSON.stringify(elements));
};

Queue.prototype.dequeue = function () {
    var elements = JSON.parse(localStorage.getItem("queue" + this.qn));
    var x = elements.shift();
    localStorage.setItem("queue" + this.qn, JSON.stringify(elements));
    return x;
};

Queue.prototype.isEmpty = function () {
    var elements = JSON.parse(localStorage.getItem("queue" + this.qn));
    return elements.length == 0;
};

Queue.prototype.length = function() {
    var elements = JSON.parse(localStorage.getItem("queue" + this.qn));
    return elements.length == 0 ? 0 : elements.length;
}

/* Classroom toolbox additions.
 *
 * The VL53L0X category is injected here at runtime rather than written into
 * ui/toolbox/esp32.xml. Mind the two shapes xhrGET hands back for a 'document'
 * response: over http it is XMLHttpRequest.responseXML, a real XMLDocument;
 * on file:// it is the pre-baked hidden element from index.html, which is an
 * Element and has no createElement of its own. Take the owning document in
 * both cases - calling response.createElement directly threw on the offline
 * build and lost the whole category.
 */
if (typeof xhrGET === 'function') {
    var classroomOriginalXhrGET = xhrGET;

    /* A missing category means the blocks are loaded but unreachable from the
       palette - a broken classroom build that looks fine until a student goes
       hunting. Say so in the app's own notification area, not just the console
       where nobody is looking. `which` names the category that failed, since
       two independent ones share this function and a hardcoded name would
       misreport which one is actually missing. */
    var classroomToolboxFailed = function (which, why, err) {
        var msg = 'Classroom toolbox: the ' + which + ' could not be added ('
                + why + '). They are loaded but will not appear in the palette.';
        console.error(msg, err || '');
        var shout = function () {
            if (typeof UI !== 'undefined' && UI['notify'] && UI['notify'].send)
                UI['notify'].send(msg);
        };
        if (document.readyState === 'complete') shout();
        else window.addEventListener('load', shout, false);
    };

    xhrGET = function(filename, responsetype, onsuccess, onfail) {
        return classroomOriginalXhrGET(filename, responsetype, function(response) {
            if (responsetype === 'document' && /toolbox\/esp32\.xml/i.test(filename)) {
                var doc = response.nodeType === 9 ? response : response.ownerDocument;
                var sensors = null;
                if (doc && typeof doc.createElement === 'function') {
                    var categories = response.querySelectorAll('category');
                    for (var i = 0; i < categories.length; i++) {
                        var name = categories[i].getAttribute('name') || '';
                        if (name.indexOf('CAT_SENSORS') !== -1) {
                            sensors = categories[i];
                            break;
                        }
                    }
                }

                /* Each category gets its own try/catch: a failure adding one
                   must not prevent the other from being attached. */
                try {
                    if (!doc || typeof doc.createElement !== 'function')
                        throw new Error('no owning document for the toolbox XML');
                    if (!sensors)
                        throw new Error('no CAT_SENSORS category to attach to');

                    if (!response.querySelector('block[type="vl53l0x_init"]')) {
                        var tofCategory = doc.createElement('category');
                        tofCategory.setAttribute('name', 'VL53L0X Time of Flight');
                        tofCategory.setAttribute('colour', '190');
                        var initBlock = doc.createElement('block');
                        initBlock.setAttribute('type', 'vl53l0x_init');
                        tofCategory.appendChild(initBlock);
                        var distanceBlock = doc.createElement('block');
                        distanceBlock.setAttribute('type', 'vl53l0x_distance');
                        tofCategory.appendChild(distanceBlock);
                        sensors.appendChild(tofCategory);

                        /* Confirm it reads back: appending into the wrong
                           document or namespace fails silently otherwise. */
                        if (!response.querySelector('block[type="vl53l0x_init"]'))
                            throw new Error('category attached but not readable back');
                    }
                } catch (e) {
                    classroomToolboxFailed('VL53L0X blocks', e.message, e);
                }

                try {
                    if (!doc || typeof doc.createElement !== 'function')
                        throw new Error('no owning document for the toolbox XML');
                    if (!sensors)
                        throw new Error('no CAT_SENSORS category to attach to');

                    if (!response.querySelector('block[type="gyro_init"]')) {
                        var gyroCategory = doc.createElement('category');
                        gyroCategory.setAttribute('name', 'MPU-6050 Gyro');
                        gyroCategory.setAttribute('colour', '20');
                        ['gyro_init', 'gyro_stop', 'gyro_reset', 'gyro_turn'].forEach(function (t) {
                            var b = doc.createElement('block');
                            b.setAttribute('type', t);
                            gyroCategory.appendChild(b);
                        });
                        sensors.appendChild(gyroCategory);

                        if (!response.querySelector('block[type="gyro_init"]'))
                            throw new Error('category attached but not readable back');
                    }
                } catch (e) {
                    classroomToolboxFailed('gyro blocks', e.message, e);
                }
                /* The Games category (Invaders, Snake, Defender, ...) is
                   injected by games.js, not here - see that file. */
            }
            onsuccess(response);
        }, onfail);
    };
}

/* Classroom OLED behaviour and I2C teaching blocks for the ESP32-C3 course. */
window.addEventListener('load', function () {
    if (typeof Blockly === 'undefined' || typeof Blockly.Python === 'undefined') return;

    /* Student-friendly GPIO labels: GPIO number plus only useful board functions. */
    if (Blockly.Blocks['pinout']) {
        var classroomOriginalPinoutInit = Blockly.Blocks['pinout'].init;
        Blockly.Blocks['pinout'].init = function() {
            classroomOriginalPinoutInit.call(this);
            var pinField = this.getField && this.getField('PIN');
            if (pinField && Array.isArray(pinField.menuGenerator_)) {
                pinField.menuGenerator_ = pinField.menuGenerator_.map(function(option) {
                    var value = String(option[1]);
                    var label = 'GPIO' + value;
                    if (value === '8') label += ' / On-board LED';
                    if (value === '9') label += ' / BOOT Btn';
                    if (value === '20') label += ' / RX';
                    if (value === '21') label += ' / TX';
                    return [label, option[1]];
                });
            }
        };
    }

    function classroomHexAddress(digits) {
        var clean = String(digits || '0').trim().replace(/^0x/i, '');
        return '0x' + (clean || '0');
    }

    Blockly.Blocks['init_oled'] = {
        init: function() {
            this.setColour(135);
            this.appendDummyInput().appendField('Init I2C SSD1306 OLED Display');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/oled.png", 55, 55, "*"));
            this.appendDummyInput()
                .appendField('I2C').appendField(new Blockly.FieldDropdown([['0', '0'], ['1', '1']]), 'I2C')
                .appendField('SDA').appendField(new Blockly.FieldNumber(0, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(0, 0, 48, 1), 'SCL');
            this.appendDummyInput()
                .appendField('Address 0x')
                .appendField(new Blockly.FieldTextInput('0'), 'ADDRESS');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Initialise an SSD1306 OLED on an I2C bus. Students must set the bus, SDA, SCL and address.');
            this.setHelpUrl('http://www.bipes.net.br');
        }
    };

    Blockly.Python['init_oled'] = function(block) {
        var i2c = block.getFieldValue('I2C') || '0';
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';
        var address = classroomHexAddress(block.getFieldValue('ADDRESS'));
        Blockly.Python.definitions_['import_i2c'] = 'from machine import Pin, I2C';
        Blockly.Python.definitions_['import_ssd'] = 'import ssd1306';
        var code = 'i2c = I2C(' + i2c + ', scl=Pin(' + scl + '), sda=Pin(' + sda + '))\n';
        code += 'oled_width = 128\n';
        code += 'oled_height = 64\n';
        code += 'oled = ssd1306.SSD1306_I2C(oled_width, oled_height, i2c, addr=' + address + ')\n';
        return code;
    };

    Blockly.Blocks['vl53l0x_init'] = {
        init: function() {
            this.setColour(190);
            this.appendDummyInput().appendField('Start VL53L0X ToF sensor');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/vl53l0x.jpg", 55, 55, "*"));
            this.appendDummyInput()
                .appendField('I2C').appendField(new Blockly.FieldDropdown([['0', '0'], ['1', '1']]), 'I2C')
                .appendField('SDA').appendField(new Blockly.FieldNumber(0, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(0, 0, 48, 1), 'SCL');
            this.appendDummyInput()
                .appendField('Address 0x')
                .appendField(new Blockly.FieldTextInput('0'), 'ADDRESS');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Initialise a VL53L0X distance sensor. Students must set the bus, SDA, SCL and address.');
        }
    };

    Blockly.Blocks['vl53l0x_distance'] = {
        init: function() {
            this.setColour(190);
            this.appendDummyInput()
                .appendField('VL53L0X distance (mm)')
                .appendField('address 0x')
                .appendField(new Blockly.FieldTextInput('0'), 'ADDRESS');
            this.setOutput(true, null);
            this.setTooltip('Read distance in millimetres. Set the sensor address first. Returns ???? when the sensor reports out of range.');
        }
    };

    function vl53AddressKey(addressDigits) {
        return String(addressDigits || '0').replace(/^0x/i, '').replace(/[^A-Za-z0-9_]/g, '_');
    }

    Blockly.Python['vl53l0x_init'] = function(block) {
        var i2c = block.getFieldValue('I2C') || '0';
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';
        var addressDigits = block.getFieldValue('ADDRESS') || '0';
        var address = classroomHexAddress(addressDigits);
        var key = vl53AddressKey(addressDigits);
        var busKey = i2c + '_' + sda + '_' + scl;
        Blockly.Python.definitions_['import_i2c'] = 'from machine import Pin, I2C';
        Blockly.Python.definitions_['import_vl53l0x_nb'] = 'from vl53l0x_nb import VL53L0X';
        var code = 'tof_i2c_' + busKey + ' = I2C(' + i2c + ', scl=Pin(' + scl + '), sda=Pin(' + sda + '))\n';
        code += 'tof_' + key + ' = VL53L0X(tof_i2c_' + busKey + ', address=' + address + ')\n';
        return code;
    };

    Blockly.Python['vl53l0x_distance'] = function(block) {
        var addressDigits = block.getFieldValue('ADDRESS') || '0';
        var key = vl53AddressKey(addressDigits);
        var reading = 'tof_' + key + '.range';
        return ['(lambda _d: "????" if _d >= 8190 else _d)(' + reading + ')', Blockly.Python.ORDER_FUNCTION_CALL];
    };

    Blockly.Python['write_oled'] = function(block) {
        var x = Blockly.Python.valueToCode(block, 'x', Blockly.Python.ORDER_ATOMIC);
        var y = Blockly.Python.valueToCode(block, 'y', Blockly.Python.ORDER_ATOMIC);
        var t = Blockly.Python.valueToCode(block, 'text', Blockly.Python.ORDER_ATOMIC);
        return 'oled.fill_rect(' + x + ', ' + y + ', len(str(' + t + ')) * 8, 8, 0)\n' +
               'oled.text(' + t + ', ' + x + ', ' + y + ')\n' +
               'oled.show()\n';
    };

    Blockly.Python['write_oled_int'] = function(block) {
        var x = Blockly.Python.valueToCode(block, 'x', Blockly.Python.ORDER_ATOMIC);
        var y = Blockly.Python.valueToCode(block, 'y', Blockly.Python.ORDER_ATOMIC);
        var value = Blockly.Python.valueToCode(block, 'value', Blockly.Python.ORDER_ATOMIC);
        return 'oled.fill_rect(' + x + ', ' + y + ', 32, 8, 0)\n' +
               'oled.text(str(' + value + '), ' + x + ', ' + y + ')\n' +
               'oled.show()\n';
    };

    /* MPU-6050 gyro: turn angle only, matching firmware/gyro.py. SDA / SCL /
       address default to 0, same as the ToF and OLED blocks above, so
       students wire up the real values themselves. */
    Blockly.Blocks['gyro_init'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput().appendField('Start MPU-6050 gyro');
            this.appendDummyInput().appendField(new Blockly.FieldImage("media/mpu6050.jpg", 55, 55, "*"));
            this.appendDummyInput()
                .appendField('I2C').appendField(new Blockly.FieldDropdown([['0', '0'], ['1', '1']]), 'I2C')
                .appendField('SDA').appendField(new Blockly.FieldNumber(0, 0, 48, 1), 'SDA')
                .appendField('SCL').appendField(new Blockly.FieldNumber(0, 0, 48, 1), 'SCL');
            this.appendDummyInput()
                .appendField('Address 0x')
                .appendField(new Blockly.FieldTextInput('0'), 'ADDRESS');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Initialise the gyro and start measuring turns in the background. KEEP THE ROBOT STILL for half a second while it calibrates. Students must set the bus, SDA, SCL and address.');
        }
    };

    Blockly.Blocks['gyro_stop'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput().appendField('Stop gyro');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Stop measuring turns and free the timer. Use at the end of a program, or before code that needs the I2C bus to itself.');
        }
    };

    Blockly.Blocks['gyro_reset'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput().appendField('Reset turn angle to 0');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Set the turn angle back to zero. Use immediately before each turn.');
        }
    };

    Blockly.Blocks['gyro_turn'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput().appendField('Turn angle in degrees (+ right, - left)');
            this.setOutput(true, null);
            this.setTooltip('Degrees turned since the last reset. Measured continuously in the background, so it reads correctly however often you check it.');
        }
    };

    Blockly.Python['gyro_init'] = function(block) {
        var i2c = block.getFieldValue('I2C') || '0';
        var sda = block.getFieldValue('SDA') || '0';
        var scl = block.getFieldValue('SCL') || '0';
        var address = classroomHexAddress(block.getFieldValue('ADDRESS'));
        Blockly.Python.definitions_['import_gyro'] =
            'from gyro import gyro_setup, gyro_stop, gyro_turn, gyro_reset';
        return 'gyro_setup(bus=' + i2c + ', sda=' + sda + ', scl=' + scl +
               ', addr=' + address + ')\n';
    };

    Blockly.Python['gyro_stop'] = function(block) {
        Blockly.Python.definitions_['import_gyro'] =
            'from gyro import gyro_setup, gyro_stop, gyro_turn, gyro_reset';
        return 'gyro_stop()\n';
    };

    Blockly.Python['gyro_reset'] = function(block) {
        Blockly.Python.definitions_['import_gyro'] =
            'from gyro import gyro_setup, gyro_stop, gyro_turn, gyro_reset';
        return 'gyro_reset()\n';
    };

    Blockly.Python['gyro_turn'] = function(block) {
        Blockly.Python.definitions_['import_gyro'] =
            'from gyro import gyro_setup, gyro_stop, gyro_turn, gyro_reset';
        return ['gyro_turn()', Blockly.Python.ORDER_FUNCTION_CALL];
    };

    /* Games category (Invaders, Snake, Defender, ...) now lives in
       games.js, split out once the embedded standalone games made this
       file's growth unbounded. See that file. */

    /* Servo + fresh ultrasonic ping, alongside the other robot_* blocks.
       All five call robot.py rather than driving the pins directly - two
       bits of code owning the same pin is how you get the intermittent
       timeouts and flaky readings that look like hardware faults. Needs
       the robot.py additions (servo(), look(), servo_off(), ping_mm(),
       look_and_measure()) - not present before firmware VERSION 0.6.1. */

    /* ---- servo: angle ------------------------------------------------- */
    Blockly.Blocks['robot_servo_angle'] = {
        init: function() {
            this.setColour(45);
            this.appendDummyInput()
                .appendField('point sensor at')
                .appendField(new Blockly.FieldAngle(90), 'ANGLE')
                .appendField('degrees');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Move the servo to an angle from 0 to 180. Carries on straight away - the servo takes about a third of a second to arrive, so use "look" instead if you are about to measure.');
        }
    };

    /* ---- servo: named position, waits for arrival ----------------------
     * Separate from the angle block on purpose. This one WAITS; that one
     * does not. Hiding that difference behind one block is how a student
     * ends up measuring mid-sweep and blaming the sensor.
     */
    Blockly.Blocks['robot_look'] = {
        init: function() {
            this.setColour(45);
            this.appendDummyInput()
                .appendField('look')
                .appendField(new Blockly.FieldDropdown([
                    ['left', 'left'],
                    ['ahead', 'ahead'],
                    ['right', 'right']
                ]), 'WHERE')
                .appendField('and wait');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Point the sensor and wait for it to get there. Waits only as long as the move needs. Use this before measuring.');
        }
    };

    /* ---- servo off ------------------------------------------------------ */
    Blockly.Blocks['robot_servo_off'] = {
        init: function() {
            this.setColour(45);
            this.appendDummyInput().appendField('let servo go limp');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Stop driving the servo. It goes quiet and stops holding position. Saves power and stops the buzzing.');
        }
    };

    /* ---- fresh ping ------------------------------------------------------
     * Timeout in milliseconds because that is what the block asks for and
     * what a student can reason about. The docs on the block say what range
     * each timeout reaches, since the relationship is not obvious.
     */
    Blockly.Blocks['robot_ping'] = {
        init: function() {
            this.setColour(45);
            this.appendDummyInput()
                .appendField('distance (mm), give up after')
                .appendField(new Blockly.FieldNumber(12, 1, 30, 1), 'TIMEOUT')
                .appendField('ms');
            this.setOutput(true, 'Number');
            this.setTooltip('Measure the distance right now. 12 ms reaches about 2 m; 6 ms about 1 m; 3 ms about 50 cm. Shorter is quicker but sees less. Returns 9999 if nothing echoes back. Point the sensor first with "look" or "point sensor at" if you want a reading in a particular direction - this block only measures, it does not aim.');
        }
    };

    /* ---- generators ------------------------------------------------------ */

    Blockly.Python['robot_servo_angle'] = function(block) {
        Blockly.Python.definitions_['import_robot'] = 'import robot';
        return 'robot.servo(' + block.getFieldValue('ANGLE') + ')\n';
    };

    Blockly.Python['robot_look'] = function(block) {
        Blockly.Python.definitions_['import_robot'] = 'import robot';
        return "robot.look('" + block.getFieldValue('WHERE') + "')\n";
    };

    Blockly.Python['robot_servo_off'] = function(block) {
        Blockly.Python.definitions_['import_robot'] = 'import robot';
        return 'robot.servo_off()\n';
    };

    Blockly.Python['robot_ping'] = function(block) {
        Blockly.Python.definitions_['import_robot'] = 'import robot';
        return ['robot.ping_mm(' + block.getFieldValue('TIMEOUT') + ')',
                Blockly.Python.ORDER_FUNCTION_CALL];
    };

    /* ---- drive at an exact duty -------------------------------------------
     * forward()'s three named speeds (slow/medium/fast) are enough for most
     * lessons; this is for students exploring what duty itself does. Goes
     * through robot.forward_at(), which uses the same trim, staggered launch,
     * gyro heading hold and grout recovery as the named-speed block.
     */
    Blockly.Blocks['robot_forward_at'] = {
        init: function() {
            this.setColour('#FFD400');
            this.appendDummyInput()
                .appendField('drive')
                .appendField(new Blockly.FieldDropdown([
                    ['forward', 'forward'],
                    ['backward', 'backward']
                ]), 'DIR')
                .appendField('at')
                .appendField(new Blockly.FieldNumber(450, 0, 550, 1), 'DUTY');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Drive forward or backward at an exact safe duty from 0 to 550. Uses the calibrated trim, gyro heading hold and grout recovery.');
        }
    };

    Blockly.Python['robot_forward_at'] = function(block) {
        Blockly.Python.definitions_['import_robot'] = 'import robot';
        var fn = block.getFieldValue('DIR') === 'backward' ? 'backward_at' : 'forward_at';
        return 'robot.' + fn + '(' + block.getFieldValue('DUTY') + ')\n';
    };

    /* ---- DevLink data passed between repeated block runs ----------------- */
    Blockly.Blocks['robot_previous_result'] = {
        init: function() {
            this.setColour('#FFD400');
            this.appendDummyInput().appendField('data from previous robot run');
            this.setOutput(true, null);
            this.setTooltip('The value returned by the previous Bluetooth run, or None on the first run.');
        }
    };

    Blockly.Python['robot_previous_result'] = function(block) {
        return ['ctx.input', Blockly.Python.ORDER_ATOMIC];
    };

    Blockly.Blocks['robot_return_result'] = {
        init: function() {
            this.setColour('#FFD400');
            this.appendValueInput('VALUE').appendField('return to next robot run');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Save a value as this run’s result. “Run again with result” passes it into the next run.');
        }
    };

    Blockly.Python['robot_return_result'] = function(block) {
        var value = Blockly.Python.valueToCode(block, 'VALUE', Blockly.Python.ORDER_NONE) || 'None';
        return '_devlink_result = ' + value + '\n';
    };

    /* Gyro motor calibration -- self-contained, nothing to upload. The whole
       calibration suite is embedded below via definitions_, same pattern as
       the standalone games in games.js. Needs robot.py and gyro.py already
       on the board - they are the robot and the sensor, not part of this
       tool, and every classroom robot already has them.

       Four actions in one block rather than four blocks: they share the
       whole KP/straight()/motor-duty machinery, and a dropdown keeps the
       Robot category from gaining four near-identical entries.
         measure breakaway   ~90s, robot pivots, needs half a metre clear.
                              RESET the board afterwards - robot.py reads
                              breakaway at import.
         set trim            Run it twice - a proportional controller
                              settles most of the way on the first pass.
         drive straight      Accelerate and hold a line for the given
                              seconds, correcting all the way.
         check straightness  Launch, run, stop, report degrees off straight.
       Calibrate on the floor the robot will actually run on. */
    var GYROCAL_SRC = [
        "def _gyrocal(action, duty, kp, secs):",
        "    # Whole calibration suite nested here, so it creates exactly one global.",
        "    # Needs robot.py and gyro.py already on the board -- they are the robot",
        "    # and the sensor, not part of this tool.",
        "",
        "    # Yaw that counts as \"the wheel moved\". A stationary calibrated gyro drifts a",
        "    # few tenths of a degree per second, so over a 400 ms burst noise is well",
        "    # under half a degree. A wheel that has just barely broken away turns the",
        "    # robot several degrees. Two is comfortably clear of one and below the other.",
        "    MOVED_DEG = 2.0",
        "",
        "    # Longer burst = less bias. The search stops at the first duty whose yaw",
        "    # clears MOVED_DEG, and a wheel only just past breakaway creeps, so the",
        "    # answer always lands somewhat ABOVE the true figure. How far above is",
        "    # MOVED_DEG / (yaw-rate-per-duty * burst), which for a plausible robot is",
        "    # ~17 duty at 400ms and ~10 at 700ms. Erring high is the safe direction for",
        "    # a launch floor -- a wheel that definitely starts beats one that sometimes",
        "    # does -- but it is bias, not noise, and worth knowing about.",
        "    BURST_MS = 700          # how long to hold each duty",
        "    SETTLE_MS = 250         # let the chassis stop rocking before reading",
        "",
        "    COARSE_STEP = 50        # bracket the breakaway",
        "    FINE_STEP = 5           # then find it properly",
        "    DUTY_MIN = 80",
        "    DUTY_MAX = 750          # above this something is wrong with the motor",
        "",
        "    REPEATS = 3             # median of three: stiction is not repeatable",
        "",
        "",
        "    def _yaw_after(ch, duty):",
        "        \"\"\"Drive one wheel at raw duty for a burst. Return degrees turned.\"\"\"",
        "        gyro.gyro_reset()",
        "        time.sleep_ms(60)               # let the reset settle",
        "        try:",
        "            # _motors, not _drive_one: this takes the reverse flags and, more",
        "            # importantly, both wheels' duty, so the other side is explicitly",
        "            # held at zero rather than left wherever it was.",
        "            if ch == \"A\":",
        "                robot._motors(duty, False, 0, False)",
        "            else:",
        "                robot._motors(0, False, duty, False)",
        "            time.sleep_ms(BURST_MS)",
        "        finally:",
        "            robot.stop()",
        "        time.sleep_ms(SETTLE_MS)",
        "        return abs(gyro.gyro_turn())",
        "",
        "",
        "    def _first_move(ch, lo, hi, step, verbose=True):",
        "        \"\"\"Lowest duty in [lo, hi] that moves the wheel, or None.\"\"\"",
        "        d = lo",
        "        while d <= hi:",
        "            moved = 0",
        "            for _ in range(REPEATS):",
        "                y = _yaw_after(ch, d)",
        "                if y >= MOVED_DEG:",
        "                    moved += 1",
        "            if verbose:",
        "                print(\"    duty %3d -> moved %d/%d\" % (d, moved, REPEATS))",
        "            # Majority, not any: one lucky nudge from a chassis still rocking",
        "            # after the previous test is not a breakaway.",
        "            if moved * 2 > REPEATS:",
        "                return d",
        "            d += step",
        "        return None",
        "",
        "",
        "    def breakaway(save=True):",
        "        \"\"\"Measure the breakaway duty of each wheel and save it.",
        "",
        "        Returns (A, B), or (None, None) if a wheel never moved.",
        "        \"\"\"",
        "        print(\"\")",
        "        print(\"== BREAKAWAY (gyro, on the floor, under load) ==\")",
        "        print(\"The robot will pivot about 30 degrees each test.\")",
        "        print(\"Clear half a metre. Same floor you will drive on.\")",
        "        print(\"\")",
        "",
        "        gyro.gyro_setup()",
        "        print(\"gyro calibrating - keep the robot still\")",
        "        time.sleep_ms(700)",
        "",
        "        found = {}",
        "        for ch in (\"A\", \"B\"):",
        "            print(\"  channel %s:\" % ch)",
        "",
        "            # Coarse pass to bracket it, so the fine pass has 10 steps not 130.",
        "            c = _first_move(ch, DUTY_MIN, DUTY_MAX, COARSE_STEP)",
        "            if c is None:",
        "                print(\"  channel %s never moved up to %d - check the motor\"",
        "                      % (ch, DUTY_MAX))",
        "                return (None, None)",
        "",
        "            # Fine pass from one coarse step below, since the answer is somewhere",
        "            # in that gap.",
        "            lo = max(DUTY_MIN, c - COARSE_STEP + FINE_STEP)",
        "            print(\"    bracketed %d..%d, refining\" % (lo, c))",
        "            f = _first_move(ch, lo, c, FINE_STEP)",
        "            found[ch] = f if f is not None else c",
        "            print(\"  channel %s breakaway = %d\" % (ch, found[ch]))",
        "",
        "        a, b = found[\"A\"], found[\"B\"]",
        "        print(\"\")",
        "        print(\"A=%d  B=%d  (difference %d)\" % (a, b, abs(a - b)))",
        "        if abs(a - b) > 100:",
        "            print(\"That is a big difference. Check for a rubbing wheel or a\")",
        "            print(\"gearbox that needs running in before trusting it.\")",
        "",
        "        if save:",
        "            robot.set_breakaway(a, b)",
        "            try:",
        "                import json",
        "                try:",
        "                    with open(robot.MAZE_CAL_FILE) as f:",
        "                        cal = json.load(f)",
        "                except (OSError, ValueError):",
        "                    cal = {}",
        "                cal[\"breakaway_A\"] = a",
        "                cal[\"breakaway_B\"] = b",
        "                with open(robot.MAZE_CAL_FILE, \"w\") as f:",
        "                    json.dump(cal, f)",
        "                print(\"saved to %s\" % robot.MAZE_CAL_FILE)",
        "            except Exception as e:",
        "                print(\"could not save:\", e)",
        "",
        "        return (a, b)",
        "",
        "",
        "    # ---------------------------------------------------------------------------",
        "    # Closed-loop straight launch",
        "    # ---------------------------------------------------------------------------",
        "",
        "    KP = 8.0                # duty per degree of heading error",
        "    RAMP_STEPS = 20",
        "    MAX_CORRECTION = 200    # never let the correction swamp the drive",
        "",
        "",
        "    def straight(target_duty, ramp_ms=500, kp=KP, verbose=False):",
        "        \"\"\"Accelerate forward to target_duty, holding a straight line.",
        "",
        "        Open-loop trim corrects the average difference between the motors. It",
        "        cannot correct the launch, because the two wheels break static friction",
        "        at slightly different moments and the robot is already a few degrees off",
        "        before either is really turning.",
        "",
        "        This watches the gyro during the ramp and moves duty from the leading",
        "        wheel to the lagging one as it goes, so the error is corrected while it",
        "        is still small.",
        "",
        "        Both wheels start AT their measured breakaway rather than at zero, so",
        "        neither spends the first part of the ramp not moving at all.",
        "        \"\"\"",
        "        a0, b0 = robot.get_breakaway()",
        "        if a0 == 0 or b0 == 0:",
        "            print(\"gyrocal: breakaway not measured - run gyrocal.breakaway() first\")",
        "            a0 = b0 = 0",
        "",
        "        left_is_a = (robot.LEFT_MOTOR == \"A\")",
        "",
        "        gyro.gyro_reset()",
        "        step_ms = max(10, ramp_ms // RAMP_STEPS)",
        "",
        "        try:",
        "            for i in range(1, RAMP_STEPS + 1):",
        "                frac = i / float(RAMP_STEPS)",
        "                base_a = a0 + (target_duty - a0) * frac",
        "                base_b = b0 + (target_duty - b0) * frac",
        "",
        "                # Positive yaw = turned right = the LEFT wheel has gone further,",
        "                # so take duty off the left and give it to the right.",
        "                err = gyro.gyro_turn()",
        "                corr = kp * err",
        "                if corr > MAX_CORRECTION:",
        "                    corr = MAX_CORRECTION",
        "                elif corr < -MAX_CORRECTION:",
        "                    corr = -MAX_CORRECTION",
        "",
        "                if left_is_a:",
        "                    da, db = base_a - corr, base_b + corr",
        "                else:",
        "                    da, db = base_a + corr, base_b - corr",
        "",
        "                da = min(max(int(da), 0), 1023)",
        "                db = min(max(int(db), 0), 1023)",
        "                robot._motors(da, False, db, False)",
        "",
        "                if verbose:",
        "                    print(\"  %2d  err %+6.1f  A %4d  B %4d\" % (i, err, da, db))",
        "                time.sleep_ms(step_ms)",
        "        except Exception:",
        "            robot.stop()",
        "            raise",
        "",
        "        return gyro.gyro_turn()",
        "",
        "",
        "    def drive_straight(target_duty, seconds, kp=KP, verbose=False):",
        "        \"\"\"Accelerate to target_duty and HOLD a straight line for `seconds`.",
        "",
        "        straight() only corrects during the ramp, and on a robot whose motors",
        "        differ by a few percent almost all the heading error accumulates",
        "        afterwards, during the cruise -- measured at 0.45 degrees from the launch",
        "        against 2.1 degrees from the following 1.2 seconds. Correcting the launch",
        "        alone therefore fixes the smaller half of the problem.",
        "",
        "        This keeps the loop running for the whole drive.",
        "        \"\"\"",
        "        straight(target_duty, kp=kp, verbose=verbose)",
        "",
        "        left_is_a = (robot.LEFT_MOTOR == \"A\")",
        "        t_end = time.ticks_add(time.ticks_ms(), int(seconds * 1000))",
        "        try:",
        "            while time.ticks_diff(t_end, time.ticks_ms()) > 0:",
        "                err = gyro.gyro_turn()",
        "                corr = kp * err",
        "                if corr > MAX_CORRECTION:",
        "                    corr = MAX_CORRECTION",
        "                elif corr < -MAX_CORRECTION:",
        "                    corr = -MAX_CORRECTION",
        "                if left_is_a:",
        "                    da, db = target_duty - corr, target_duty + corr",
        "                else:",
        "                    da, db = target_duty + corr, target_duty - corr",
        "                robot._motors(min(max(int(da), 0), 1023), False,",
        "                              min(max(int(db), 0), 1023), False)",
        "                time.sleep_ms(25)",
        "        finally:",
        "            robot.stop()",
        "        return gyro.gyro_turn()",
        "",
        "",
        "    def autotrim(target_duty=800, seconds=2.5, kp=32):",
        "        \"\"\"Drive straight under gyro control, then keep the correction as trim.",
        "",
        "        Replaces the l/r/s guessing game in bench.trim(). A proportional",
        "        controller settles with a standing correction equal to the motor",
        "        mismatch -- that standing correction IS the trim, so rather than",
        "        discarding it when the drive ends, measure it and store it.",
        "",
        "        Afterwards even open-loop forward() drives straighter, because the",
        "        imbalance has been taken out at source.",
        "        \"\"\"",
        "        gyro.gyro_setup()",
        "        time.sleep_ms(700)",
        "",
        "        left_is_a = (robot.LEFT_MOTOR == \"A\")",
        "        samples = []",
        "",
        "        gyro.gyro_reset()",
        "        straight(target_duty, kp=kp)",
        "",
        "        t_end = time.ticks_add(time.ticks_ms(), int(seconds * 1000))",
        "        try:",
        "            while time.ticks_diff(t_end, time.ticks_ms()) > 0:",
        "                err = gyro.gyro_turn()",
        "                corr = kp * err",
        "                if corr > MAX_CORRECTION:",
        "                    corr = MAX_CORRECTION",
        "                elif corr < -MAX_CORRECTION:",
        "                    corr = -MAX_CORRECTION",
        "                if left_is_a:",
        "                    da, db = target_duty - corr, target_duty + corr",
        "                else:",
        "                    da, db = target_duty + corr, target_duty - corr",
        "                robot._motors(min(max(int(da), 0), 1023), False,",
        "                              min(max(int(db), 0), 1023), False)",
        "                samples.append(corr)",
        "                time.sleep_ms(25)",
        "        finally:",
        "            robot.stop()",
        "",
        "        if len(samples) < 8:",
        "            print(\"gyrocal: run too short to measure trim\")",
        "            return robot.get_trim()",
        "",
        "        # Second half only: the first half is still settling.",
        "        tail = samples[len(samples) // 2:]",
        "        corr = sum(tail) / len(tail)",
        "",
        "        a, b = robot.get_trim()",
        "        if left_is_a:",
        "            na, nb = a * (1 - corr / target_duty), b * (1 + corr / target_duty)",
        "        else:",
        "            na, nb = a * (1 + corr / target_duty), b * (1 - corr / target_duty)",
        "",
        "        # Clamp to the same range robot.py allows, and never scale UP past 1.0 --",
        "        # trim takes duty away from the strong side rather than asking the weak",
        "        # side for more than it has.",
        "        na = min(max(na, 0.5), 1.0)",
        "        nb = min(max(nb, 0.5), 1.0)",
        "",
        "        robot.set_trim(na, nb)",
        "        robot.save_trim()",
        "        print(\"steady correction %+.1f duty -> trim A=%.3f B=%.3f (saved)\"",
        "              % (corr, na, nb))",
        "        return (na, nb)",
        "",
        "",
        "    def check(target_duty=800, run_ms=1200):",
        "        \"\"\"Launch, hold, stop. Print how far off straight it ended up.",
        "",
        "        Run it a few times. A consistent bias means the trim is wrong; scatter",
        "        with no bias means the surface or the battery, not the calibration.",
        "        \"\"\"",
        "        gyro.gyro_setup()",
        "        time.sleep_ms(700)",
        "",
        "        print(\"launching...\")",
        "        try:",
        "            straight(target_duty)",
        "            time.sleep_ms(run_ms)",
        "        finally:",
        "            robot.stop()",
        "        time.sleep_ms(400)",
        "",
        "        err = gyro.gyro_turn()",
        "        print(\"ended %+.1f degrees off straight\" % err)",
        "        if abs(err) < 3:",
        "            print(\"  good\")",
        "        elif err > 0:",
        "            print(\"  drifting right\")",
        "        else:",
        "            print(\"  drifting left\")",
        "        return err",
        "",
        "    if action == 'breakaway':",
        "        breakaway()",
        "    elif action == 'autotrim':",
        "        autotrim(duty, secs, kp)",
        "    elif action == 'straight':",
        "        drive_straight(duty, secs, kp)",
        "    elif action == 'check':",
        "        check(duty)",
        "    else:",
        "        print('gyrocal: unknown action', action)",
        ""
    ].join('\n');

    Blockly.Blocks['gyro_calibrate'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput()
                .appendField('gyro motor')
                .appendField(new Blockly.FieldDropdown([
                    ['full safe calibration', 'breakaway'],
                    ['recalibrate motors', 'autotrim'],
                    ['safe straight run', 'straight'],
                    ['safe straightness check', 'check']
                ]), 'ACTION');
            this.appendDummyInput()
                .appendField('speed')
                .appendField(new Blockly.FieldNumber(300, 0, 300, 10), 'DUTY')
                .appendField('for')
                .appendField(new Blockly.FieldNumber(2, 0.5, 8, 0.5), 'SECS')
                .appendField('s');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Compatibility block for older projects. Both calibration choices now run the current bidirectional safe calibration. Straight tests use gyro hold and the 300-duty mobile ceiling.');
        }
    };

    Blockly.Python['gyro_calibrate'] = function(block) {
        var action = block.getFieldValue('ACTION');
        var duty = Math.min(300, Math.max(0,
            Number(block.getFieldValue('DUTY') || 300)));
        var secs = Math.min(8, Math.max(0,
            Number(block.getFieldValue('SECS') || 2)));

        Blockly.Python.definitions_['import_robot'] = 'import robot';
        if (action === 'breakaway' || action === 'autotrim') {
            return "_devlink_result = {'calibration': robot.characterise()}\n";
        }
        if (action === 'check') {
            Blockly.Python.definitions_['import_gyro'] = 'import gyro';
            return 'robot.forward_at(' + duty + ')\n'
                 + 'robot.wait(' + secs + ')\n'
                 + 'robot.stop()\n'
                 + '_gyro_error = gyro.gyro_turn()\n'
                 + "print('straightness yaw: %.2f deg' % _gyro_error)\n"
                 + "_devlink_result = {'yaw_deg': _gyro_error, 'duty': " + duty
                 + ", 'seconds': " + secs + "}\n";
        }
        return 'robot.forward_at(' + duty + ')\n'
             + 'robot.wait(' + secs + ')\n'
             + 'robot.stop()\n';
    };

    var MMCAL_SRC = [
        "def _mmcal(action, degrees, duty, secs):",
        "    # Whole module nested here, so it creates exactly one global.",
        "    # Needs robot.py and gyro.py already on the board.",
        "",
        "    CAL_FILE = \"mmcal.json\"",
        "",
        "    # --- characterisation sweep ------------------------------------------------",
        "    # Harrison: \"They are likely to be small values like 5-20%.\" On a 1023 scale",
        "    # that is 50-200, but an N20 on carpet needs more to move at all, so the",
        "    # sweep starts higher and the fit discards points that did not move.",
        "    SWEEP = (250, 350, 450, 550, 650, 750)",
        "    SPIN_MS = 900          # long enough to reach steady state: several x Tm",
        "    SAMPLE_MS = 20         # matches the gyro sampler; no point going faster",
        "    SETTLE_MS = 400        # let it stop between runs",
        "",
        "    # --- controller design -----------------------------------------------------",
        "    ZETA = 0.7             # Harrison: \"a slightly underdamped system with an",
        "                           # overshoot of a couple of percent\"",
        "    TDS = 0.25             # settling time. See note above about 20ms sampling.",
        "    LOOP_MS = 20",
        "",
        "    MAX_DIFF = 400         # cap on the duty difference the controller may ask for",
        "",
        "",
        "    def _spin(duty, ms):",
        "        \"\"\"Spin on the spot at a fixed duty difference. Returns [(t_ms, deg/s)].",
        "",
        "        One motor forward, one back, exactly as Harrison describes. Any other",
        "        control must be off -- he is explicit that the mouse is \"allowed to",
        "        accelerate up to a constant angular velocity\" with nothing interfering.",
        "        \"\"\"",
        "        out = []",
        "        gyro.gyro_reset()",
        "        last_deg = 0.0",
        "        t0 = time.ticks_ms()",
        "        try:",
        "            robot._motors(duty, False, duty, True)      # A fwd, B reverse",
        "            while True:",
        "                t = time.ticks_diff(time.ticks_ms(), t0)",
        "                if t >= ms:",
        "                    break",
        "                time.sleep_ms(SAMPLE_MS)",
        "                t = time.ticks_diff(time.ticks_ms(), t0)",
        "                deg = gyro.gyro_turn()",
        "                if out:",
        "                    dt = (t - out[-1][0]) / 1000.0",
        "                    if dt > 0:",
        "                        out.append((t, (deg - last_deg) / dt))",
        "                else:",
        "                    out.append((t, 0.0))",
        "                last_deg = deg",
        "        finally:",
        "            robot.stop()",
        "        time.sleep_ms(SETTLE_MS)",
        "        return out",
        "",
        "",
        "    def _steady(trace):",
        "        \"\"\"Steady-state rate: mean of the last third of the run.",
        "",
        "        Harrison: \"Record that value by averaging over some suitable period -",
        "        say 1 second or so\".",
        "        \"\"\"",
        "        if len(trace) < 6:",
        "            return 0.0",
        "        tail = trace[len(trace) * 2 // 3:]",
        "        return sum(abs(r) for _, r in tail) / len(tail)",
        "",
        "",
        "    def _time_constant(trace, steady):",
        "        \"\"\"Tm from the 63% point.",
        "",
        "        Harrison: \"finding the time where each graph passes through an angular",
        "        velocity that is 63% of the steady state value. This is because",
        "        1-exp(-1) = 0.632.\"",
        "        \"\"\"",
        "        if steady <= 0:",
        "            return None",
        "        target = 0.632 * steady",
        "        for t, r in trace:",
        "            if abs(r) >= target:",
        "                return t / 1000.0",
        "        return None",
        "",
        "",
        "    def _fit(points):",
        "        \"\"\"Least squares y = m.x + c over (duty, rate). Returns (Km, deadband).\"\"\"",
        "        n = len(points)",
        "        if n < 2:",
        "            return (None, None)",
        "        sx = sum(p[0] for p in points)",
        "        sy = sum(p[1] for p in points)",
        "        sxx = sum(p[0] * p[0] for p in points)",
        "        sxy = sum(p[0] * p[1] for p in points)",
        "        den = n * sxx - sx * sx",
        "        if den == 0:",
        "            return (None, None)",
        "        m = (n * sxy - sx * sy) / den",
        "        c = (sy - m * sx) / n",
        "        dead = -c / m if m else None      # x-intercept: the drive-system losses",
        "        return (m, dead)",
        "",
        "",
        "    def gains(km, tm, zeta=ZETA, tds=TDS):",
        "        \"\"\"PD gains from the measured plant.",
        "",
        "        Plant Km/(s(1+Tm.s)) under PD gives",
        "            s^2 + ((1+Km.Kd)/Tm).s + Km.Kp/Tm = 0",
        "        Matching s^2 + 2.zeta.wn.s + wn^2, with wn from the 2% settling time:",
        "            Kp = wn^2.Tm/Km",
        "            Kd = (2.zeta.wn.Tm - 1)/Km",
        "        \"\"\"",
        "        wn = 4.0 / (zeta * tds)",
        "        kp = wn * wn * tm / km",
        "        kd = (2 * zeta * wn * tm - 1) / km",
        "        return (kp, kd if kd > 0 else 0.0)",
        "",
        "",
        "    def characterise(save=True, verbose=True):",
        "        \"\"\"Measure Km, Tm and the deadband. The robot spins on the spot.",
        "",
        "        Needs only its own footprint of floor -- no straight run.",
        "        \"\"\"",
        "        print(\"\")",
        "        print(\"== DRIVE CHARACTERISATION (Harrison method) ==\")",
        "        print(\"The robot spins on the spot. It needs no room to travel.\")",
        "        print(\"\")",
        "        gyro.gyro_setup()",
        "        print(\"gyro calibrating - keep the robot still\")",
        "        time.sleep_ms(800)",
        "",
        "        pts = []",
        "        tms = []",
        "        for duty in SWEEP:",
        "            tr = _spin(duty, SPIN_MS)",
        "            ss = _steady(tr)",
        "            tm = _time_constant(tr, ss)",
        "            if verbose:",
        "                print(\"  duty %4d -> %7.1f deg/s   Tm %s\"",
        "                      % (duty, ss, (\"%.3f s\" % tm) if tm else \"-\"))",
        "            # A point where nothing turned tells the fit nothing except that it",
        "            # was below the deadband, and including it drags the line down.",
        "            if ss > 5.0:",
        "                pts.append((duty, ss))",
        "                if tm:",
        "                    tms.append(tm)",
        "",
        "        if len(pts) < 2:",
        "            print(\"  not enough points moved - is the robot on the floor?\")",
        "            return None",
        "",
        "        km, dead = _fit(pts)",
        "        tm = sum(tms) / len(tms) if tms else None",
        "        if km is None or tm is None:",
        "            print(\"  fit failed\")",
        "            return None",
        "",
        "        kp, kd = gains(km, tm)",
        "",
        "        print(\"\")",
        "        print(\"  Km       %.3f deg/s per duty count\" % km)",
        "        print(\"  Tm       %.3f s\" % tm)",
        "        print(\"  deadband %.0f duty  (drive-system losses)\" % dead)",
        "        print(\"  kP       %.3f\" % kp)",
        "        print(\"  kD       %.4f\" % kd)",
        "        print(\"\")",
        "        print(\"  settling %.2f s, zeta %.1f\" % (TDS, ZETA))",
        "",
        "        cal = {\"Km\": km, \"Tm\": tm, \"deadband\": dead, \"kP\": kp, \"kD\": kd}",
        "        if save:",
        "            try:",
        "                import json",
        "                with open(CAL_FILE, \"w\") as f:",
        "                    json.dump(cal, f)",
        "                print(\"  saved to %s\" % CAL_FILE)",
        "            except Exception as e:",
        "                print(\"  could not save:\", e)",
        "        return cal",
        "",
        "",
        "    def _load():",
        "        try:",
        "            import json",
        "            with open(CAL_FILE) as f:",
        "                return json.load(f)",
        "        except (OSError, ValueError):",
        "            return None",
        "",
        "",
        "    # ---------------------------------------------------------------------------",
        "    # The controller. One PD loop, used for both turning and holding a line.",
        "    # ---------------------------------------------------------------------------",
        "",
        "    def _pd(target_deg, base_duty, timeout_ms, tol_deg, hold_ms, cal):",
        "        \"\"\"PD position control on heading.",
        "",
        "        Harrison's parallel form, verbatim in structure:",
        "",
        "            errorOld = error;",
        "            error = setPos - currentPos;",
        "            PWM   = kP * error;",
        "            PWM  += kD * (error - errorOld);",
        "",
        "        base_duty 0 means spin on the spot; anything else drives forward at that",
        "        duty while the controller steers.",
        "        \"\"\"",
        "        kp, kd = cal[\"kP\"], cal[\"kD\"]",
        "        dead = cal[\"deadband\"]",
        "",
        "        err_old = target_deg - gyro.gyro_turn()",
        "        t0 = time.ticks_ms()",
        "        in_tol_since = None",
        "",
        "        try:",
        "            while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:",
        "                err = target_deg - gyro.gyro_turn()",
        "",
        "                diff = kp * err + kd * (err - err_old) * (1000.0 / LOOP_MS)",
        "                err_old = err",
        "",
        "                # Below the deadband nothing happens at all, so a small demand",
        "                # would simply be ignored. Lift it over the threshold instead --",
        "                # this is what the intercept from the fit is for.",
        "                if diff > 1:",
        "                    diff += dead",
        "                elif diff < -1:",
        "                    diff -= dead",
        "",
        "                if diff > MAX_DIFF:",
        "                    diff = MAX_DIFF",
        "                elif diff < -MAX_DIFF:",
        "                    diff = -MAX_DIFF",
        "",
        "                if base_duty == 0:",
        "                    # Spinning on the spot: SAME magnitude both wheels, opposite",
        "                    # directions. Computing da = +diff and db = -diff and then",
        "                    # taking the sign of each separately does not work -- db",
        "                    # comes out negative, its reverse flag reads False, and both",
        "                    # wheels drive forward. The robot then drives away in a",
        "                    # straight line instead of turning, which is exactly what it",
        "                    # did the first time this was tested.",
        "                    mag = int(min(abs(diff), 1023))",
        "                    robot._motors(mag, diff < 0, mag, diff > 0)",
        "                else:",
        "                    da = base_duty + diff",
        "                    db = base_duty - diff",
        "                    robot._motors(int(min(max(da, 0), 1023)), False,",
        "                                  int(min(max(db, 0), 1023)), False)",
        "",
        "                if abs(err) <= tol_deg:",
        "                    if in_tol_since is None:",
        "                        in_tol_since = time.ticks_ms()",
        "                    elif time.ticks_diff(time.ticks_ms(), in_tol_since) >= hold_ms:",
        "                        return err",
        "                else:",
        "                    in_tol_since = None",
        "",
        "                time.sleep_ms(LOOP_MS)",
        "        finally:",
        "            if base_duty == 0:",
        "                robot.stop()",
        "        return target_deg - gyro.gyro_turn()",
        "",
        "",
        "    def turn(degrees, tol=2.0):",
        "        \"\"\"Turn on the spot. + is right, - is left.\"\"\"",
        "        cal = _load()",
        "        if cal is None:",
        "            print(\"mmcal: run characterise() first\")",
        "            return None",
        "        gyro.gyro_setup()",
        "        time.sleep_ms(600)",
        "        gyro.gyro_reset()",
        "        err = _pd(degrees, 0, 4000, tol, 100, cal)",
        "        robot.stop()",
        "        print(\"turn %+.0f -> off by %+.1f deg\" % (degrees, err))",
        "        return err",
        "",
        "",
        "    def forward(duty, seconds, tol=1.0):",
        "        \"\"\"Drive forward holding the heading it started on.",
        "",
        "        Same controller as turn(), target zero. That is the point of",
        "        characterising rotation: steering and turning are the same problem.",
        "        \"\"\"",
        "        cal = _load()",
        "        if cal is None:",
        "            print(\"mmcal: run characterise() first\")",
        "            return None",
        "        gyro.gyro_setup()",
        "        time.sleep_ms(600)",
        "        gyro.gyro_reset()",
        "        err = _pd(0.0, duty, int(seconds * 1000), tol, 10 ** 9, cal)",
        "        robot.stop()",
        "        print(\"drove %.1fs -> off by %+.1f deg\" % (seconds, err))",
        "        return err",
        "",
        "    if action == 'characterise':",
        "        characterise()",
        "    elif action == 'turn':",
        "        turn(degrees)",
        "    elif action == 'forward':",
        "        forward(duty, secs)",
        "    else:",
        "        print('mmcal: unknown action', action)",
        ""
    ].join('\n');

    Blockly.Blocks['mmcal'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput()
                .appendField('motor')
                .appendField(new Blockly.FieldDropdown([
                    ['safe characterise', 'characterise'],
                    ['safe measured turn', 'turn'],
                    ['safe straight test', 'forward']
                ]), 'ACTION');
            this.appendDummyInput()
                .appendField('turn')
                .appendField(new Blockly.FieldNumber(90, -360, 360, 5), 'DEGREES')
                .appendField('deg  (+ right)');
            this.appendDummyInput()
                .appendField('drive at')
                .appendField(new Blockly.FieldNumber(300, 0, 300, 10), 'DUTY')
                .appendField('for')
                .appendField(new Blockly.FieldNumber(2, 0.5, 8, 0.5), 'SECS')
                .appendField('s');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Compatibility motor test for older projects. It now uses the current robot API, gyro-measured turns, bidirectional calibration, and the 300-duty mobile limit.');
        }
    };

    Blockly.Python['mmcal'] = function(block) {
        var action = block.getFieldValue('ACTION');
        var degrees = Number(block.getFieldValue('DEGREES') || 90);
        var duty = Math.min(300, Math.max(0,
            Number(block.getFieldValue('DUTY') || 300)));
        var secs = Math.min(8, Math.max(0,
            Number(block.getFieldValue('SECS') || 2)));

        Blockly.Python.definitions_['import_robot'] = 'import robot';
        if (action === 'characterise') return 'robot.characterise()\n';
        if (action === 'turn') {
            var direction = degrees < 0 ? 'left' : 'right';
            var angle = Math.min(450, Math.abs(degrees));
            return "robot.turn_degrees('" + direction + "', " + angle + ")\n";
        }
        return 'robot.forward_at(' + duty + ')\n'
             + 'robot.wait(' + secs + ')\n'
             + 'robot.stop()\n';
    };

    /* Calibrate motors -- one block, one button. Calls robot.characterise(),
       which measures this robot's motor gain, time constant and deadband by
       spinning on the spot, then derives the steering and turn gains from
       them. Needs robot.py 0.7.0+ and gyro.py on the board.

       Run once per robot. After that the ordinary forward and turn blocks
       use the result automatically - it is saved on the board and robot.py
       loads it at import. Then take this block back out of the program.

       Shows Km, Tm and the deadband on the OLED when it finishes, because
       the robot is on the floor and unplugged at that moment and the
       console is not readable. */
    Blockly.Blocks['robot_calibrate'] = {
        init: function() {
            this.setColour(20);
            this.appendDummyInput().appendField('Calibrate motors');
            this.appendDummyInput()
                .appendField(new Blockly.FieldImage("media/calibrate.jpg", 55, 55, "*"));
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Run once per robot on the floor with the ultrasonic sensor pointing ahead and at least 25 cm clear. It tests both turn directions for about a minute, filters floor bumps, and saves the steering calibration. Remove this block afterwards.');
        }
    };

    Blockly.Python['robot_calibrate'] = function(block) {
        Blockly.Python.definitions_['import_robot'] = 'import robot';
        return "_devlink_result = {'calibration': robot.characterise()}\n";
    };
});
