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
 * Each OLED write block cleans only the area it is about to use, then writes
 * and shows the framebuffer. This lets separate blocks share one screen.
 *
 * Number fields reserve 4 characters (32 pixels) so changing values do not
 * leave old digits behind. Text clears only the width of the text it writes.
 */
window.addEventListener('load', function () {
    if (typeof Blockly === 'undefined' || typeof Blockly.Python === 'undefined') {
        return;
    }

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
