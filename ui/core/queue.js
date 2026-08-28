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
   //console.log('queue' + num);
}

Queue.prototype.enqueue = function (e) {
   //console.log('push queue' + this.qn);
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

/*
Queue.prototype.peek = function () {
    var elements = JSON.parse(localStorage.getItem("queue"));
    return !isEmpty() ? elements[0] : undefined;
};
*/

Queue.prototype.length = function() {
    var elements = JSON.parse(localStorage.getItem("queue" + this.qn));
    return elements.length;
}


/*
 * Classroom toolbox additions.
 *
 * queue.js loads after ui.js (where xhrGET is defined) but before the page
 * load event creates the Blockly workspace. Wrap toolbox loading here so the
 * ESP32 toolbox gains the VL53L0X blocks without having to maintain a second
 * large copy of esp32.xml.
 */
if (typeof xhrGET === 'function') {
    var classroomOriginalXhrGET = xhrGET;
    xhrGET = function(filename, responsetype, onsuccess, onfail) {
        return classroomOriginalXhrGET(filename, responsetype, function(response) {
            try {
                if (responsetype === 'document' && /toolbox\/esp32\.xml/i.test(filename)) {
                    var categories = response.querySelectorAll('category');
                    var sensors = null;
                    for (var i = 0; i < categories.length; i++) {
                        var name = categories[i].getAttribute('name') || '';
                        if (name.indexOf('CAT_SENSORS') !== -1) {
                            sensors = categories[i];
                            break;
                        }
                    }

                    if (sensors && !response.querySelector('block[type="vl53l0x_init"]')) {
                        var tofCategory = response.createElement('category');
                        tofCategory.setAttribute('name', 'VL53L0X Time of Flight');
                        tofCategory.setAttribute('colour', '190');

                        var initBlock = response.createElement('block');
                        initBlock.setAttribute('type', 'vl53l0x_init');
                        tofCategory.appendChild(initBlock);

                        var distanceBlock = response.createElement('block');
                        distanceBlock.setAttribute('type', 'vl53l0x_distance');
                        tofCategory.appendChild(distanceBlock);

                        sensors.appendChild(tofCategory);
                    }
                }
            } catch (e) {
                console.warn('Could not add classroom VL53L0X toolbox blocks:', e);
            }
            onsuccess(response);
        }, onfail);
    };
}


/*
 * Classroom OLED behaviour and I2C teaching blocks for the ESP32-C3 course.
 */
window.addEventListener('load', function () {
    if (typeof Blockly === 'undefined' || typeof Blockly.Python === 'undefined') {
        return;
    }

    /*
     * OLED init: keep the original OLED artwork and controls, and add the
     * visible I2C address. Classroom defaults are I2C 0, SDA 5, SCL 6,
     * address 0x3C.
     */
    Blockly.Blocks['init_oled'] = {
        init: function() {
            this.setColour(135);
            this.appendDummyInput()
                .appendField('Init I2C SSD1306 OLED Display');

            // Preserve the original BIPES OLED picture.
            this.appendDummyInput()
                .appendField(new Blockly.FieldImage(
                    "media/oled.png",
                    55,
                    55,
                    "*"));

            this.appendDummyInput()
                .appendField('I2C')
                .appendField(new Blockly.FieldDropdown([['0', '0'], ['1', '1']]), 'I2C')
                .appendField('SDA')
                .appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL')
                .appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.appendDummyInput()
                .appendField('Address')
                .appendField(new Blockly.FieldTextInput('0x3C'), 'ADDRESS');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Initialise an SSD1306 OLED on an I2C bus. Default address is 0x3C.');
            this.setHelpUrl('http://www.bipes.net.br');
        }
    };

    Blockly.Python['init_oled'] = function(block) {
        var i2c = block.getFieldValue('I2C') || '0';
        var sda = block.getFieldValue('SDA') || '5';
        var scl = block.getFieldValue('SCL') || '6';
        var address = block.getFieldValue('ADDRESS') || '0x3C';

        Blockly.Python.definitions_['import_i2c'] = 'from machine import Pin, I2C';
        Blockly.Python.definitions_['import_ssd'] = 'import ssd1306';

        var code = 'i2c = I2C(' + i2c + ', scl=Pin(' + scl + '), sda=Pin(' + sda + '))\n';
        code += 'oled_width = 128\n';
        code += 'oled_height = 64\n';
        code += 'oled = ssd1306.SSD1306_I2C(oled_width, oled_height, i2c, addr=' + address + ')\n';
        return code;
    };

    /*
     * VL53L0X Time-of-Flight sensor.
     * The address field means the CURRENT address the sensor answers on.
     * 0x29 is the normal power-up address. Different addresses can therefore
     * be selected when a project has configured more than one sensor.
     */
    Blockly.Blocks['vl53l0x_init'] = {
        init: function() {
            this.setColour(190);
            this.appendDummyInput()
                .appendField('Start VL53L0X ToF sensor');
            this.appendDummyInput()
                .appendField('I2C')
                .appendField(new Blockly.FieldDropdown([['0', '0'], ['1', '1']]), 'I2C')
                .appendField('SDA')
                .appendField(new Blockly.FieldNumber(5, 0, 48, 1), 'SDA')
                .appendField('SCL')
                .appendField(new Blockly.FieldNumber(6, 0, 48, 1), 'SCL');
            this.appendDummyInput()
                .appendField('Address')
                .appendField(new Blockly.FieldTextInput('0x29'), 'ADDRESS');
            this.setPreviousStatement(true, null);
            this.setNextStatement(true, null);
            this.setTooltip('Initialise a VL53L0X distance sensor. Standard address is 0x29.');
        }
    };

    Blockly.Blocks['vl53l0x_distance'] = {
        init: function() {
            this.setColour(190);
            this.appendDummyInput()
                .appendField('VL53L0X distance (mm)')
                .appendField('address')
                .appendField(new Blockly.FieldTextInput('0x29'), 'ADDRESS');
            this.setOutput(true, null);
            this.setTooltip('Read distance in millimetres. Returns ???? when the sensor reports out of range.');
        }
    };

    function vl53AddressKey(address) {
        return String(address || '0x29')
            .replace(/^0x/i, '')
            .replace(/[^A-Za-z0-9_]/g, '_');
    }

    Blockly.Python['vl53l0x_init'] = function(block) {
        var i2c = block.getFieldValue('I2C') || '0';
        var sda = block.getFieldValue('SDA') || '5';
        var scl = block.getFieldValue('SCL') || '6';
        var address = block.getFieldValue('ADDRESS') || '0x29';
        var key = vl53AddressKey(address);
        var busKey = i2c + '_' + sda + '_' + scl;

        Blockly.Python.definitions_['import_i2c'] = 'from machine import Pin, I2C';
        Blockly.Python.definitions_['import_vl53l0x_nb'] = 'from vl53l0x_nb import VL53L0X';

        var code = 'tof_i2c_' + busKey + ' = I2C(' + i2c + ', scl=Pin(' + scl + '), sda=Pin(' + sda + '))\n';
        code += 'tof_' + key + ' = VL53L0X(tof_i2c_' + busKey + ', address=' + address + ')\n';
        return code;
    };

    Blockly.Python['vl53l0x_distance'] = function(block) {
        var address = block.getFieldValue('ADDRESS') || '0x29';
        var key = vl53AddressKey(address);
        var reading = 'tof_' + key + '.range';
        return ['(lambda _d: "????" if _d >= 8190 else _d)(' + reading + ')', Blockly.Python.ORDER_FUNCTION_CALL];
    };

    /*
     * OLED write blocks: clean only the area they are about to use, then show.
     * This lets separate blocks share one screen.
     */
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
