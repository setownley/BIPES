/* Gyro turn-angle blocks for the classroom BIPES fork.
 *
 * Three blocks, one job: how far has the robot turned.
 *   + degrees = right, - degrees = left.
 *
 * Pitch and roll are deliberately not exposed. The board lies flat and the
 * robot does not tilt, so they would only be two more things a student can
 * pick by mistake.
 *
 * INTEGRATION: block and generator definitions follow the VL53L0X pattern in
 * ui/core/queue.js -- registered inside a load listener so this overrides
 * any earlier definition, same file layout, own <script> tag and own
 * Cache-Control rule in _headers so a stale copy cannot leave the blocks
 * loaded but unreachable.
 *
 * UNLIKE VL53L0X, the toolbox category is NOT runtime-injected. It is a
 * static "Gyro" category in ui/toolbox/esp32.xml, sibling to "Inertial
 * Measurement". queue.js's xhrGET patch only knows how to inject into
 * esp32.xml and only looks for CAT_SENSORS; extending it for a second
 * category would have meant either duplicating that patch (the file://
 * branch was only fixed once, in queue.js, and a second copy is a second
 * place for the same bug) or teaching one patch to inject two unrelated
 * categories. A static entry in the XML has neither problem and needs no
 * injection at all.
 *
 * Uses ui/media/mpu6050_gyro.png for the setup block -- distinct from
 * media/mpu6050.png, which belongs to the older init_mpu6050 block set.
 */

window.addEventListener('load', function () {

  var IMPORT = 'from gyro import gyro_setup, gyro_turn, gyro_reset';

  /* ---- setup -----------------------------------------------------------
   * Defaults are what this robot uses: GPIO5 = SDA, GPIO6 = SCL, 0x68 with
   * AD0 tied low. A block that runs as soon as it is dragged out beats one
   * that needs three fields filled first.
   */
  Blockly.Blocks['gyro_setup'] = {
    init: function () {
      this.appendDummyInput()
          .appendField(new Blockly.FieldImage(
              'media/mpu6050_gyro.png', 110, 110, 'MPU-6050 gyro module'));
      this.appendDummyInput()
          .appendField('set up gyro');
      this.appendDummyInput()
          .appendField('SDA')
          .appendField(new Blockly.FieldNumber(5, 0, 21, 1), 'SDA')
          .appendField('SCL')
          .appendField(new Blockly.FieldNumber(6, 0, 21, 1), 'SCL')
          .appendField('address')
          .appendField(new Blockly.FieldTextInput('0x68'), 'ADDR');
      this.setPreviousStatement(true, null);
      this.setNextStatement(true, null);
      this.setColour(20);
      this.setTooltip(
          'Wakes the gyro and measures its resting offset. KEEP THE ROBOT ' +
          'STILL while this runs -- about half a second. Use once, at the ' +
          'start of your program.');
    }
  };

  /* ---- reset ----------------------------------------------------------- */
  Blockly.Blocks['gyro_reset'] = {
    init: function () {
      this.appendDummyInput()
          .appendField('reset turn angle to 0');
      this.setPreviousStatement(true, null);
      this.setNextStatement(true, null);
      this.setColour(20);
      this.setTooltip(
          'Sets the turn angle back to zero. Use this immediately before ' +
          'every turn, then turn until the angle reaches the value you want.');
    }
  };

  /* ---- read -------------------------------------------------------------
   * The tooltip says to read it in a loop because that is not optional. The
   * angle is the turn rate added up over time and only advances when read;
   * a single read after a delay counts the whole delay as one sample and
   * gives a wrong answer.
   */
  Blockly.Blocks['gyro_turn'] = {
    init: function () {
      this.appendDummyInput()
          .appendField('turn angle (+ right, - left)');
      this.setOutput(true, 'Number');
      this.setColour(20);
      this.setTooltip(
          'Degrees turned since the last reset. Positive is right, ' +
          'negative is left. READ THIS IN A LOOP -- it only updates when ' +
          'you read it, so checking it once after a delay gives a wrong ' +
          'answer.');
    }
  };

  /* ---- generators ------------------------------------------------------ */

  Blockly.Python['gyro_setup'] = function (block) {
    Blockly.Python.definitions_['import_gyro'] = IMPORT;
    return 'gyro_setup(sda=' + block.getFieldValue('SDA') +
           ', scl=' + block.getFieldValue('SCL') +
           ', addr=' + block.getFieldValue('ADDR') + ')\n';
  };

  Blockly.Python['gyro_reset'] = function (block) {
    Blockly.Python.definitions_['import_gyro'] = IMPORT;
    return 'gyro_reset()\n';
  };

  Blockly.Python['gyro_turn'] = function (block) {
    Blockly.Python.definitions_['import_gyro'] = IMPORT;
    return ['gyro_turn()', Blockly.Python.ORDER_FUNCTION_CALL];
  };

});
