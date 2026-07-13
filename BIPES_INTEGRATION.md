# BIPES fork integration — custom blocks for robot.py v0.1.0

Two complete blocks are specified below: one statement block with a dropdown
(`drive forward`) and one boolean-free value block (`distance (cm)`), because
the two patterns differ and every other block you build is a copy of one of
them.

**Confidence framing for this whole file:** the snippets use the classic
Blockly API (`Blockly.Blocks[...]` / `Blockly.Python[...]` /
`Blockly.Python.definitions_`), which is what BIPES's pinned older Blockly
uses per the handover's source inspection. MEDIUM confidence until pasted:
I have not executed these against your fork. The handover's own advice
applies — open an existing block in `core/block_definitions.js` and
`core/generator_stubs.js` and confirm these snippets match its shape before
trusting them. Do NOT use the modern Block Factory output (known not to
paste cleanly into BIPES's pinned Blockly).

---

## 1. Block appearance — paste into `core/block_definitions.js`

```javascript
Blockly.Blocks['robot_forward'] = {
  init: function() {
    this.appendDummyInput()
        .appendField("drive forward")
        .appendField(new Blockly.FieldDropdown([
            ["slow", "slow"],
            ["medium", "medium"],
            ["fast", "fast"]
        ]), "SPEED");
    this.setPreviousStatement(true, null);
    this.setNextStatement(true, null);
    this.setColour(120);
    this.setTooltip("Drive both wheels forward");
  }
};

Blockly.Blocks['robot_distance'] = {
  init: function() {
    this.appendDummyInput()
        .appendField("distance (cm)");
    this.setOutput(true, "Number");
    this.setColour(230);
    this.setTooltip("How far away is the thing in front? 999 means nothing seen");
  }
};
```

## 2. Generated Python — paste into `core/generator_stubs.js`

```javascript
Blockly.Python['robot_forward'] = function(block) {
  Blockly.Python.definitions_['import_robot'] = 'import robot';
  var speed = block.getFieldValue('SPEED');
  return "robot.forward('" + speed + "')\n";
};

Blockly.Python['robot_distance'] = function(block) {
  Blockly.Python.definitions_['import_robot'] = 'import robot';
  return ['robot.distance_cm()', Blockly.Python.ORDER_FUNCTION_CALL];
};
```

Notes:
- `definitions_['import_robot']` is keyed, so `import robot` is emitted
  exactly once no matter how many robot blocks are used or in what order.
- Statement blocks return a **string ending in \n**; value blocks return a
  **[code, order] pair**. Mixing these up is the classic Blockly mistake and
  fails silently (block generates nothing).
- The dropdown's machine values are already lowercase, matching
  `robot.SPEEDS` keys exactly — no transformation, no way to mismatch.

## 3. Palette entry — paste into `toolbox/<your-board>.xml`

Inside a new category (and delete the categories you don't want kids to see,
including the asyncio, Timer, GPIO-interrupt, and raw ADC blocks):

```xml
<category name="Robot" colour="120">
  <block type="robot_forward"></block>
  <block type="robot_distance"></block>
</category>
```

## 4. Safety wrapper — try/finally around every student program

Goal: BIPES's stop button sends Ctrl-C (KeyboardInterrupt); without a
wrapper, motors keep running at their last speed. Locate the Python
generator's `finish` function (standard Blockly name:
`Blockly.Python.finish`, which receives the generated code and prepends the
collected `definitions_`). Modify it so the *body* (not the imports) is
wrapped:

```javascript
// inside Blockly.Python.finish, after imports/definitions are split out:
code = 'try:\n' +
       Blockly.Python.prefixLines(code, Blockly.Python.INDENT) +
       'finally:\n' +
       Blockly.Python.INDENT + 'import robot\n' +
       Blockly.Python.INDENT + 'robot.stop()\n';
```

**LOW-MEDIUM confidence, two separate unknowns, both testable in minutes:**
1. Whether BIPES's fork of `finish` matches stock Blockly closely enough for
   this edit — inspect the actual function in your fork first.
2. Whether a KeyboardInterrupt raised during `time.sleep()` inside
   `robot.wait()` reliably reaches the `finally` on MicroPython v1.28 —
   bench-test: run a program that drives forward then waits 30 s, hit stop,
   confirm motors cut. If it fails, the fallback is the RESET button
   (boot.py guarantees motors-off) — acceptable, but test before class.

## 5. Verification checklist for the block layer

1. Open the fork locally with `python3 -m http.server` (menus load via
   fetch and need a server).
2. Drag `drive forward [fast]` + `distance (cm)` into a program, open the
   generated-code view, confirm output is exactly:

   ```python
   import robot
   robot.forward('fast')
   ```
   (distance block inside e.g. an if-comparison → `robot.distance_cm()`)
3. Confirm `import robot` appears once even with five robot blocks.
4. Run against a provisioned board over USB; confirm the robot moves and
   the stop button (or RESET, per item 4.2) halts it.
