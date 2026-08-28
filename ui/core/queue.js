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
 * Classroom OLED behaviour for the ESP32-C3 course.
 *
 * The stock BIPES OLED generators are inconsistent: write_oled() calls
 * oled.show(), while write_oled_int() only writes to the framebuffer.
 * For younger students, both blocks should simply mean "put this on the
 * screen".  These overrides run after generator_stubs.js has loaded.
 *
 * Both text and values now do: clear -> write -> show.
 */
window.addEventListener('load', function () {
    if (typeof Blockly === 'undefined' || typeof Blockly.Python === 'undefined') {
        return;
    }

    Blockly.Python['write_oled'] = function(block) {
        var x = Blockly.Python.valueToCode(block, 'x', Blockly.Python.ORDER_ATOMIC);
        var y = Blockly.Python.valueToCode(block, 'y', Blockly.Python.ORDER_ATOMIC);
        var t = Blockly.Python.valueToCode(block, 'text', Blockly.Python.ORDER_ATOMIC);

        return 'oled.fill(0)\n' +
               'oled.text(' + t + ', ' + x + ', ' + y + ')\n' +
               'oled.show()\n';
    };

    Blockly.Python['write_oled_int'] = function(block) {
        var x = Blockly.Python.valueToCode(block, 'x', Blockly.Python.ORDER_ATOMIC);
        var y = Blockly.Python.valueToCode(block, 'y', Blockly.Python.ORDER_ATOMIC);
        var value = Blockly.Python.valueToCode(block, 'value', Blockly.Python.ORDER_ATOMIC);

        return 'oled.fill(0)\n' +
               'oled.text(str(' + value + '), ' + x + ', ' + y + ')\n' +
               'oled.show()\n';
    };
});
