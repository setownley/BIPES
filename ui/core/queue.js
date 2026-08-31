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
       where nobody is looking. */
    var classroomToolboxFailed = function (why, err) {
        var msg = 'Classroom toolbox: the VL53L0X blocks could not be added ('
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
                try {
                    var doc = response.nodeType === 9 ? response : response.ownerDocument;
                    if (!doc || typeof doc.createElement !== 'function')
                        throw new Error('no owning document for the toolbox XML');

                    var categories = response.querySelectorAll('category');
                    var sensors = null;
                    for (var i = 0; i < categories.length; i++) {
                        var name = categories[i].getAttribute('name') || '';
                        if (name.indexOf('CAT_SENSORS') !== -1) {
                            sensors = categories[i];
                            break;
                        }
                    }
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
                    classroomToolboxFailed(e.message, e);
                }
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
});
