'use strict';

/*Handles the protocol's switch between webbluetooth, webserial and websocket*/
class mux {
  /**
   * Init the mux class as Channel.mux, will check if it has been loaded as HTTPS, HTTP or locally ("file:") to handle browser policies for the protocols.
   */
  constructor () {
    this.isLocalFile = false;
    if(!window.location.origin.includes('/127.0.0.1') || window.location.protocol == 'file:') {
      switch (window.location.protocol) {
        case 'file:':
          this.available = ['webserial', 'websocket', 'webbluetooth'];
          this.currentChannel = 'webserial';
          this.isLocalFile = true;
        break;
        case 'https:':
          this.available = ['webserial', 'webbluetooth'];
          this.currentChannel = 'webserial';
        break;
        case 'http:':
          this.available = ['websocket'];
          this.currentChannel = 'websocket';
        break;
      }
    } else {
      this.available = ['webserial', 'websocket', 'webbluetooth'];
      this.currentChannel = 'webserial';
    }

    this.ifunavailable = {
      webserial: ['https://bipes.net.br/beta2/ui', 'the HTTPS version'],
      websocket: ['http:///bipes.net.br/beta2/ui', 'the HTTP version'],
      webbluetooth: ['https://bipes.net.br/beta2/ui', 'the HTTPS version']
    }
  }
	/**
   * Switch the target protocol if available, see mux.constructor
   * @param {string} channel_ - the protocol to be switched to
   */
  switch (channel_) {
    if (this.available.includes(channel_)) {
      this.currentChannel = channel_;
      mux.disconnect ();
      this.connect ();

      } else if (this.ifunavailable [channel_] != undefined) {
        let msg = `The channel ${channel_} is not yet available in this version, but at ${this.ifunavailable [channel_] [1]}, would you like to be redirected there?`;
        if (confirm(msg)) {
          window.location.replace(this.ifunavailable [channel_] [0]);
        } else {
          UI ['channel-panel'].button.className = `icon ${this.currentChannel}`
        }
    } else {
      alert(`The channel ${channel_} is not yet available in this version.`);
    }
  }

	/**
   * Connect using the target protocol, call as Channel.mux.connect()
   */
  connect () {
    switch (this.currentChannel) {
      case 'websocket':
        Channel ['websocket'].connect(UI ['workspace'].websocket.url.value, UI ['workspace'].websocket.pass.value);
      break;
      case 'webserial':
        Channel ['webserial'].connect();
      break;
      case 'webbluetooth':
        Channel ['webbluetooth'].connect();
      break;
    }
  }
	/**
   *  Disconnect using the target protocol, call as mux.disconnect()
   */
  static disconnect () {
    if (Channel ['websocket'].connected) {
      Channel ['websocket'].ws.close();
    } else if (Channel ['webserial'].connected) {
      Channel ['webserial'].disconnect();
    } else if (Channel ['webbluetooth'].connected) {
      Channel ['webbluetooth'].disconnect();
    }
  }
  /**
   * Return if a device is connected via any protocol, call as mux.connected()
   * @returns {boolean} True if a device is connected via any protocol
   */
  static connected () {
    if (Channel ['websocket'].connected || Channel ['webserial'].connected || Channel ['webbluetooth'].connected)
      return true;
    else
      return false;
  }
	/**
   * Send data to the buffer of the target protocol, to be sent to the device with the target protocol.
   * A callback function can be passed and will be called after the MicroPython REPL ">>> " charset is detected.
   * This means understanding how your code executes is crucial. Call as mux.bufferPush()
   * @param {string} code - the code to be sent to the device with the target protocol
   * @param {function} callback - the callback function to be called when the  code has been executed.
   */
  static bufferPush (code, callback) {
    let textArray;
    if (typeof code == 'object')
      textArray = code;
    else if (typeof code == 'string') {
      if (Channel ['websocket'].connected) {
        textArray = code.replace(/\r\n|\n/gm, '\r').match(/(.|[\r]){1,10}/g);
      } else if (Channel ['webserial'].connected) {
        var pattern_ = new RegExp(`(.|[\r]){1,${Channel ['webserial'].packetSize}}`, 'g')
        textArray = code.replace(/\r\n|\n/gm, '\r').match(pattern_);
      } else if (Channel ['webbluetooth'].connected) {
        var pattern_ = new RegExp(`(.|[\r]){1,`, 'g')
        textArray = code.replace(/\r\n|\n/gm, '\r').match(/(.|[\r]){1,5}/g);
      }
    }

    if (Channel ['websocket'].connected) {
      Channel ['websocket'].buffer_ = Channel ['websocket'].buffer_.concat(textArray);
      if (callback != undefined)
        Channel ['websocket'].completeBufferCallback.push(callback);
    }  else if (Channel ['webserial'].connected) {
      Channel ['webserial'].buffer_ = Channel ['webserial'].buffer_.concat(textArray);
      if (callback != undefined)
        Channel ['webserial'].completeBufferCallback.push(callback);
    } else if (Channel ['webbluetooth'].connected) {
      Channel ['webbluetooth'].buffer_ = Channel ['webbluetooth'].buffer_.concat(textArray);
      if (callback != undefined)
        Channel ['webbluetooth'].completeBufferCallback.push(callback);
    } else
      UI ['notify'].send(MSG['notConnected']);
  }

	/**
   * Send data to the first position of the buffer of the target protocol, to be sent to the device with the target protocol. This means will it'll be executed as soon as possible, is useful for reset commands.
   * @param {string} code - the code to be sent immediatally to the device with the target protocol
   */
  static bufferUnshift (code) {
    if (Channel ['websocket'].connected) {
      Channel ['websocket'].buffer_.unshift(code);
    }  else if (Channel ['webserial'].connected) {
      Channel ['webserial'].buffer_.unshift(code);
    } else if (Channel ['webbluetooth'].connected) {
      Channel ['webbluetooth'].buffer_.unshift(code);
    } else
      UI ['notify'].send(MSG['notConnected']);
  }

	/**
   * Clears the buffer of the connected protocol, code won't be sent.
   */
  static clearBuffer () {
    if (Channel ['websocket'].connected) {
      Channel ['websocket'].buffer_ = [];
    }  else if (Channel ['webserial'].connected) {
      Channel ['webserial'].buffer_ = [];
      Channel ['webserial'].completeBufferCallback = [];
    } else if (Channel ['webbluetooth'].connected) {
      Channel ['webbluetooth'].buffer_ = [];
    } else
      UI ['notify'].send(MSG['notConnected']);
  }
}

/*Handles the websocket protocol*/
class websocket {
	/**
   * Init the websocket, stored as Channel.websocket
   */
  constructor () {
    this.ws;
    this.watcher;
    /**Store the code to be sent to the device*/
    this.buffer_ = [];
    this.connected = false;
    this.completeBufferCallback = [];
  }

	/**
   * Runs every 50ms to check if there is code to be sent in the :js:attr:`websocket#buffer_` (appended with :js:func:`mux.bufferPush()`)
   */
  watch () {
    if (this.ws.bufferedAmount == 0) {
      if (this.buffer_.length > 0) {
        UI ['progress'].remain(this.buffer_.length);
        try {
          if (['Uint8Array', 'String', 'Number'].includes(this.buffer_[0].constructor.name))
          this.ws.send (this.buffer_[0]);
          this.buffer_.shift();
        } catch (e) {
          UI ['notify'].log(e);
        }
      } else {
        UI ['progress'].end();
      }
    }
  }

	/**
   * Connect using websocket protocol.
   * @param {string} url - url/IP of the device
   * @param {string} pass - password to connect to the device
   */
  connect (url, pass) {
    UI ['workspace'].connecting ();
    this.ws = new WebSocket(url);
    this.ws.binaryType = 'arraybuffer';
    this.ws.onopen = () => {
      term.on();
      term.write('\x1b[31mWelcome to BIPES Project using MicroPython!\x1b[m\r\n');

      term.write('\x1b[31mSending password...\x1b[m\r\n');
      this.ws.send(pass + '\n\n'); //this.buffer_.push(pass);

      this.connected = true;
      UI ['workspace'].websocket.url.disabled = true;

      this.ws.onmessage = (event) => {
        if (event.data instanceof ArrayBuffer) {
          var data = new Uint8Array(event.data);
          console.log('binary state = ' + Files.binary_state);
          switch (Files.binary_state) {
            case 11:
              // first response for put
              if (Tool.decode_resp(data) == 0) {
                // send file data in chunks
                for (var offset = 0; offset < Files.put_file_data.length; offset += 1024) {
                  this.ws.send(Files.put_file_data.slice(offset, offset + 1024));
                }
              Files.binary_state = 12;
              }
            break;
            case 12:
              // final response for put
              if (Tool.decode_resp(data) == 0) {
                files.update_file_status('Sent ' + Files.put_file_name + ', ' + Files.put_file_data.length + ' bytes');
                if (Files.put_file_queue && Files.put_file_queue.length)
                  setTimeout (() => {Files.put_file_next()}, 0);  // multi-file save
                else
                  Files.listFiles();
              } else {
                files.update_file_status('Failed sending ' + Files.put_file_name);
              }
              Files.binary_state = 0;
            break;

            case 21:
              // first response for get
              console.log('get 1');
              if (Tool.decode_resp(data) == 0) {
                console.log('get 2');
                Files.binary_state = 22;
                var rec = new Uint8Array(1);
                rec[0] = 0;
              this.ws.send(rec);
            }
            break;
            case 22:
              // file data
              var sz = data[0] | (data[1] << 8);
              if (data.length == 2 + sz) {
                // we assume that the data comes in single chunks
                if (sz == 0) {
                  // end of file
                  Files.binary_state = 23;
                } else {
                  // accumulate incoming data to get_file_data
                  var new_buf = new Uint8Array(Files.get_file_data.length + sz);
                  new_buf.set(Files.get_file_data);
                  new_buf.set(data.slice(2), Files.get_file_data.length);
                  Files.get_file_data = new_buf;
                  files.update_file_status('Getting ' + Files.get_file_name + ', ' + Files.get_file_data.length + ' bytes');

                  var rec = new Uint8Array(1);
                  rec[0] = 0;
                  this.ws.send(rec);
                }
              } else {
                Files.binary_state = 0;
              }
            break;
            case 23:
              // final response
              if (Tool.decode_resp(data) == 0) {
                files.update_file_status('Got ' + Files.get_file_name + ', ' + Files.get_file_data.length + ' bytes');
                if (!Files.viewOnly)
                  saveAs(new Blob([Files.get_file_data], {type: "application/octet-stream"}), Files.get_file_name);
                else
                  Tool.updateSourceCode(new Blob([Files.get_file_data], {type: "text/plain"}), Files.get_file_name);
              } else {
                files.update_file_status('Failed getting ' + Files.get_file_name);
              }
              Files.binary_state = 0;
            break;
            case 31:
              // first (and last) response for GET_VER
              console.log('GET_VER', data);
              Files.binary_state = 0;
            break;
          }
        }
        term.write(event.data);
        if (typeof event.data == 'string') {
          Tool.bipesVerify ();
          if (event.data.includes(">>> ")) {
            UI ['workspace'].runButton.status = true;
            UI ['workspace'].runButton.dom.className = 'icon';
            UI ['workspace'].toolbarButton.className = 'icon medium';
            if (this.completeBufferCallback.length > 0) {
              try {
                this.completeBufferCallback [0] ();
                this.completeBufferCallback.shift ();
              } catch (e) {
                UI ['notify'].log(e);
              }
            }
          } else if (event.data.includes("Access denied")) {
            //WebSocket might close before receiving this message, so won't trigger.
            UI ['notify'].send("Wrong board password.");
          } else if (UI ['workspace'].runButton.status == true) {
            UI ['workspace'].receiving ();
          }
        }
        Files.received_string = Files.received_string.concat(event.data);
      }

      this.watcher = setInterval(this.watch.bind(this), 50);
    }
    this.ws.onclose = () => {
      if (term)
        term.write('\x1b[31mDisconnected\x1b[m\r\n');
      term.off();
      this.buffer_ = [];
      this.connected = false;
      UI ['workspace'].runAbort();
      clearInterval(this.watcher);
    }
  }
}

/*Handles the websocket protocol*/
class webserial {
	/**
   * Init the webserial, stored as Channel.websocket
   */
  constructor () {
    this.port;
    this.watcher;
    this.watcherConnected_;
    /**Store the code to be sent to the device*/
    this.buffer_ = [];
    this.connected = false;
    this.completeBufferCallback = [];
    this.last4chars = '';
    this.encoder = new TextEncoder();
    this.appendStream = undefined;
    this.shouldListen = true;
    this.packetSize = 100;
    this.speed = 115200;
  }

	/**
   * Runs every 50ms to check if there is code to be sent in the :js:attr:`webserial#buffer_` (appended with :js:func:`mux.bufferPush()`)
   */
  watch () {
    if (this.port && this.port.writable && this.port.writable.locked == false) {
      if (this.buffer_.length > 0) {
        UI ['progress'].remain(this.buffer_.length);
        try {
		      this.serialWrite(this.buffer_ [0]);
        } catch (e) {
          UI ['notify'].log(e);
        }
      } else {
        UI ['progress'].end();
      }
    }
  }

	/**
   * Connect using webserial protocol, will ask user permission for the serial port.
   */
  connect () {
    if (typeof navigator.serial == "undefined") {
      UI ['notify'].send(MSG['notAvailableFlag'].replaceAll('$1', 'WebSerial API'));
      term.write(MSG['notAvailableFlag'].replaceAll('$1', 'WebSerial API'));
      return;
    }
    navigator.serial.requestPort ().then((port) => {
      UI ['workspace'].connecting ();
      this.port = port;
      this.port.open({baudRate: [this.speed] }).then(() => {
        const appendStream = new WritableStream({
          write(chunk) {
            if(Channel ['webserial'].shouldListen) {
              if (typeof chunk == 'string') {
                Tool.bipesVerify ();
                //data comes in chunks, keep last 4 chars to check MicroPython REPL string
                Channel ['webserial'].last4chars = Channel ['webserial'].last4chars.concat(chunk.substr(-4,4)).substr(-4,4)
                if (Channel ['webserial'].last4chars.includes(">>> ")) {
                  UI ['workspace'].runButton.status = true;
                  UI ['workspace'].runButton.dom.className = 'icon';
                  UI ['workspace'].toolbarButton.className = 'icon medium';
                  if (Channel ['webserial'].completeBufferCallback.length > 0) {
                    try {
                      Channel ['webserial'].completeBufferCallback [0] ();
                    } catch (e) {
                      UI ['notify'].log(e);
                    }
                    Channel ['webserial'].completeBufferCallback.shift ();
                  }
                } else if (UI ['workspace'].runButton.status == true) {
                  UI ['workspace'].receiving ();
                }
                Files.received_string = Files.received_string.concat(chunk);
              }
              term.write(chunk);
            }
          }
        });
        this.port.readable
        .pipeThrough(new TextDecoderStream())
        .pipeTo(appendStream);


        this.connect_ ();

        this.resetBoard ();

      }).catch((e) => {
        if (e.code == 11) {
          this.connect_ ();
          this.resetBoard ();
          this.shouldListen = true;
        }
        UI ['notify'].log(e);
      });

    }).catch((e) => {
        UI ['notify'].log(e);
    });
  }
  /**
   * User interface styling for when connected via webserial protocol.
   */
  connect_ () {
    term.on();
    term.write('\x1b[31mConnected using Web Serial API !\x1b[m\r\n');
    this.connected=true;
    if (UI ['workspace'].runButton.status == true)
        UI ['workspace'].receiving ();

    this.watcher = setInterval(this.watch.bind(this), 50);
  }
  /**
   * Disconnect device connected with webserial protocol.
   */
  disconnect () {
    const writer = this.port.writable.getWriter();
    writer.close().then(() => {
      this.port.close().then(() => {
          this.port = undefined;
        }).catch((e) => {
          UI ['notify'].log(e);
          writer.abort();
          this.port = undefined;
          this.shouldListen = false;
        })
         if (term)
          term.write('\x1b[31mDisconnected\x1b[m\r\n');
        this.buffer_ = [];
        this.last4chars = '';
        this.connected = false;
        clearInterval(this.watcher);
        term.off();
        UI ['workspace'].runAbort();
    })

  }
  /**
   * Reset board on connect with webserial protocol,
   * action enabled by a checkbox on the user interface.
   */
  resetBoard () {
    setTimeout(() => {
      if (UI ['workspace'].resetBoard.checked) {
        term.write('\x1b[31mResetting the board...\x1b[m\r\n');
        this.serialWrite ('\x04');
      } else
        this.serialWrite ('\x03');
    },50);
  }

	/**
   * Directly send code via webserial, normally called by this.watch()
   * @param {(Uint8Array|string|number)} data - code to be sent via webserial
   */
  serialWrite (data) {
    let dataArrayBuffer = undefined;
    switch (data.constructor.name) {
      case 'Uint8Array':
        dataArrayBuffer = data;
      break;
      case 'String':
      case 'Number':
        dataArrayBuffer = this.encoder.encode(data);
      break;
    }
    if (this.port && this.port.writable && dataArrayBuffer != undefined) {
      const writer = this.port.writable.getWriter();
      writer.write(dataArrayBuffer).then (() => {writer.releaseLock(); this.buffer_.shift ()});
	  }
	}
}

/*Handles the webbluetooth protocol*/
class webbluetooth {
	/**
   * Init the webbluetooth, stored as Channel.websocket
   */
  constructor () {
    this.device = undefined;
    this.nusService = undefined;
    this.txCharacteristic = undefined;
    this.rxCharacteristic = undefined;
    this.sending = false;
    this.watcher;
    /**Store the code to be sent to the device*/
    this.buffer_ = [];
    this.connected = false;
    this.completeBufferCallback = [];
    this.last4chars = '';
    this.devLink = false;
    this.devLinkLineBuffer = '';
    this.devLinkWaiters = [];
    this.devLinkTerminalWaiters = [];
    this.devLinkLastResult = undefined;
    this.devLinkCommandTimeoutMs = 10000;
    this.devLinkUploadRetryDelayMs = 150;
    this.devLinkRunTimeoutMs = 180000;
    this.devLinkRecoveryDelayMs = 250;
    this.devLinkMotorSafeDelayMs = 10000;
    this.devLinkCalibrationSafeDelayMs = 180000;
    this.devLinkHeartbeat = undefined;
    this.devLinkHeartbeatPending = false;
    this.devLinkBusyCount = 0;
    this.encoder = new TextEncoder();
    this.decoder = new TextDecoder();
  }

  static get ServiceUUID () {return '6e400001-b5a3-f393-e0a9-e50e24dcca9e';}
  static get RXUUID  () {return '6e400002-b5a3-f393-e0a9-e50e24dcca9e';}
  static get TXUUID  () {return '6e400003-b5a3-f393-e0a9-e50e24dcca9e';}

	/**
   * Runs every 50ms to check if there is code to be sent in the :js:attr:`webbluetooth#buffer_` (appended with :js:func:`mux.bufferPush()`)
   */
  watch () {
    if(this.device && this.device.gatt.connected) {
      if (this.buffer_.length >= 1 && !this.sending) {
        try {
          this.sendNextChunk(this.buffer_[0]);
        } catch (e) {
          UI ['notify'].log(e);
        }
      }
    }
  }

	/**
   * Directly send code via webbluetooth, normally called by this.watch()
   * uses a promise to handshake sent chunks, will retry in 500ms if a chunk fails
   * @param {string} operation - code to be sent via webbluetooth
   */
  sendNextChunk (operation) {
    return new Promise((resolve, reject) => {
      this.sending = true;
      let size = new ArrayBuffer(operation.length);
      const value = new Uint8Array(size);
      value.set(operation.split('').map(l => l.charCodeAt(0)), 0);
      this.rxCharacteristic.writeValue(value).then(() => {
        this.buffer_.shift();
        if (this.buffer_.length > 0) {
          this.sendNextChunk (this.buffer_[0]);
          UI ['progress'].remain(this.buffer_.length);
        } else {
          this.sending = false;
          UI ['progress'].end()
        }
      }).catch(e => {
        UI ['notify'].log (e);
        return Promise.resolve()
        .then(() => this.delayPromise(500))
        // Retry once
        .then(() => this.rxCharacteristic.writeValue(value)).catch((e) => {
        this.buffer_ = [];
        UI ['notify'].log (e);
        if (e == "NetworkError: Failed to execute 'writeValue' on 'BluetoothRemoteGATTCharacteristic': GATT Server is disconnected. Cannot perform GATT operations. (Re)connect first with `device.gatt.connect`.")
        UI ['notify'].send ("Lost Bluetooth connection.");
        });
      });
    });
  }

  delayPromise(delay) {
    return new Promise(resolve => {
        setTimeout(resolve, delay);
    });
  }

  devLinkHeartbeatTick() {
    if (!this.connected || !this.devLink || this.devLinkBusyCount
        || this.devLinkHeartbeatPending || this.devLinkWaiters.length
        || this.devLinkTerminalWaiters.length) return;
    this.devLinkHeartbeatPending = true;
    this.devLinkWrite({op: 'status'}, 'status', 5000)
      .catch(error => UI ['notify'].log('Robot heartbeat: ' + error.message))
      .finally(() => {this.devLinkHeartbeatPending = false;});
  }

  devLinkWrite(message, expectedType='ack', timeoutMs=this.devLinkCommandTimeoutMs) {
    const operation = message.op;
    return new Promise((resolve, reject) => {
      const waiter = {operation: operation, type: expectedType,
                      resolve: resolve, reject: reject, timer: undefined};
      waiter.timer = setTimeout(() => {
        this.devLinkWaiters = this.devLinkWaiters.filter(w => w !== waiter);
        reject(new Error('Bluetooth robot did not answer ' + operation));
      }, timeoutMs);
      this.devLinkWaiters.push(waiter);
      const bytes = this.encoder.encode(JSON.stringify(message));
      const write = this.rxCharacteristic.writeValueWithResponse
        ? this.rxCharacteristic.writeValueWithResponse(bytes)
        : this.rxCharacteristic.writeValue(bytes);
      write.catch(error => {
        clearTimeout(waiter.timer);
        this.devLinkWaiters = this.devLinkWaiters.filter(w => w !== waiter);
        reject(error);
      });
    });
  }

  devLinkBase64(bytes) {
    let binary = '';
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    return btoa(binary);
  }

  async devLinkUpload(source) {
    const raw = this.encoder.encode(source);
    const digest = await crypto.subtle.digest('SHA-256', raw);
    const sha = Array.from(new Uint8Array(digest))
      .map(value => value.toString(16).padStart(2, '0')).join('');
    let lastError;
    for (let attempt = 0; attempt < 3; attempt++) {
      try {
        // Restarting with begin also works with an older board supervisor if
        // the bytes landed but a chunk ACK did not.
        await this.devLinkWrite({op: 'begin', size: raw.length, sha: sha});
        const chunkSize = 120;  // safely below the board's 512-byte command buffer
        let sequence = 0;
        for (let offset = 0; offset < raw.length; offset += chunkSize) {
          const data = this.devLinkBase64(raw.slice(offset, offset + chunkSize));
          await this.devLinkWrite({op: 'chunk', n: sequence++, d: data});
          if (UI && UI['progress']) UI['progress'].remain(raw.length - offset);
        }
        await this.devLinkWrite({op: 'commit'});
        return;
      } catch (error) {
        lastError = error;
        if (attempt < 2) await this.delayPromise(this.devLinkUploadRetryDelayMs);
      }
    }
    throw lastError || new Error('Bluetooth upload failed');
  }

  async devLinkSetInput(value) {
    const raw = this.encoder.encode(JSON.stringify(value));
    if (raw.length > 320) throw new Error('Robot input is limited to 320 bytes');
    await this.devLinkWrite({op: 'input', d: this.devLinkBase64(raw)});
  }

  devLinkWaitForTerminal(timeoutMs=this.devLinkRunTimeoutMs) {
    return new Promise((resolve, reject) => {
      const waiter = {resolve: resolve, reject: reject, timer: undefined};
      waiter.timer = setTimeout(() => {
        this.devLinkTerminalWaiters = this.devLinkTerminalWaiters
          .filter(item => item !== waiter);
        reject(new Error('Final Bluetooth result was not received'));
      }, timeoutMs);
      this.devLinkTerminalWaiters.push(waiter);
    });
  }

  async devLinkRecoverOutcome(runId) {
    let lastError;
    let previousFingerprint = null;
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        // The board retains its last terminal state. This recovers a result
        // when the final notification (or one fragment of it) was lost.
        const snapshot = await this.devLinkWrite({op: 'result'}, 'result');
        const outcome = snapshot.outcome;
        if (outcome && outcome.run_id === runId) {
          const fingerprint = JSON.stringify(outcome);
          if (fingerprint === previousFingerprint) return outcome;
          previousFingerprint = fingerprint;
          lastError = new Error('Confirming retained robot result');
        }
        if (!snapshot.running) {
          if (!outcome || outcome.run_id !== runId) {
            throw new Error('Robot stopped without a retained result');
          }
        }
      } catch (error) {
        lastError = error;
      }
      await this.delayPromise(this.devLinkRecoveryDelayMs);
    }
    throw lastError || new Error('Could not recover the robot result');
  }

  devLinkMotorSafeDelay(source) {
    // Generated Robot blocks call the runtime through the `robot` module.
    // Motor switching on this ESP32-C3 layout can poison an actively-chatty
    // Windows notification session, so physical runs are accepted once,
    // left completely quiet, then read back from retained state. Sensor,
    // display and ordinary MicroPython programs keep live terminal output.
    if (/robot\.characterise\s*\(/.test(source)) {
      return this.devLinkCalibrationSafeDelayMs;
    }
    const motion = /robot\.(?:forward|forward_at|backward|backward_at|turn|turn_degrees|turn90|nudge|maze|follow_line|raw_forward|_drive_one)\s*\(/;
    return motion.test(source) ? this.devLinkMotorSafeDelayMs : 0;
  }

  async devLinkListFiles() {
    const reply = await this.devLinkWrite({op: 'files'}, 'files');
    return reply.items || [];
  }

  async devLinkReadFile(name) {
    this.devLinkBusyCount++;
    try {
      const info = await this.devLinkWrite(
        {op: 'file_info', name: name}, 'file_info');
      const expectedSize = Number(info.size);
      const chunks = [];
      let received = 0;
      while (received < expectedSize) {
        const reply = await this.devLinkWrite(
          {op: 'file_read', name: name, offset: received, length: 180}, 'file');
        if (Number(reply.offset) !== received) {
          throw new Error('Robot returned an unexpected file offset');
        }
        const binary = atob(reply.data || '');
        const block = new Uint8Array(binary.length);
        for (let index = 0; index < binary.length; index++) {
          block[index] = binary.charCodeAt(index);
        }
        if (!block.length && !reply.eof) {
          throw new Error('Robot returned an empty file chunk');
        }
        chunks.push(block);
        received += block.length;
        files.update_file_status('Getting ' + name + '... ' + received
                                 + '/' + expectedSize + ' bytes');
        if (reply.eof) break;
      }
      const body = new Uint8Array(received);
      let offset = 0;
      chunks.forEach(block => { body.set(block, offset); offset += block.length; });
      const digest = await crypto.subtle.digest('SHA-256', body);
      const actualHash = Array.from(new Uint8Array(digest))
        .map(value => value.toString(16).padStart(2, '0')).join('');
      if (body.length !== expectedSize || actualHash !== info.sha256) {
        throw new Error('Downloaded file failed size/SHA-256 verification');
      }
      return body;
    } finally {
      this.devLinkBusyCount = Math.max(0, this.devLinkBusyCount - 1);
    }
  }

  async devLinkResolveStoredResult(outcome) {
    const manifest = outcome && outcome.result;
    if (!manifest || typeof manifest !== 'object' || !manifest.stored_file) {
      return outcome;
    }
    const body = await this.devLinkReadFile(String(manifest.stored_file));
    const digest = await crypto.subtle.digest('SHA-256', body);
    const actualHash = Array.from(new Uint8Array(digest))
      .map(value => value.toString(16).padStart(2, '0')).join('');
    if (body.length !== Number(manifest.bytes)
        || actualHash !== String(manifest.sha256).toLowerCase()) {
      throw new Error('Stored robot result did not match its manifest');
    }
    let decoded;
    try {
      decoded = JSON.parse(new TextDecoder().decode(body));
    } catch (error) {
      throw new Error('Stored robot result is not valid JSON');
    }
    return Object.assign({}, outcome, {result: decoded});
  }

  async runProgram(source, input) {
    if (!this.devLink) throw new Error('The connected Bluetooth device is not a DevLink robot');
    this.devLinkBusyCount++;
    UI ['workspace'].receiving();
    UI ['progress'].start(Math.max(1, source.length));
    try {
      await this.devLinkUpload(source);
      // Explicit null prevents a previous run-again value leaking into a
      // normal click of the Run button.
      await this.devLinkSetInput(input === undefined ? null : input);
      const motorSafeDelay = this.devLinkMotorSafeDelay(source);
      const terminal = motorSafeDelay ? null : this.devLinkWaitForTerminal();
      const runAck = await this.devLinkWrite(
        {op: 'run', quiet: motorSafeDelay > 0});
      let outcome;
      if (motorSafeDelay) {
        term.write('[motor-safe run: BLE quiet during movement]\r\n');
        await this.delayPromise(motorSafeDelay);
        outcome = await this.devLinkRecoverOutcome(runAck.run_id);
      } else {
        try {
          outcome = await terminal;
        } catch (error) {
          term.write('[recovering final robot result]\r\n');
          outcome = await this.devLinkRecoverOutcome(runAck.run_id);
        }
      }
      outcome = await this.devLinkResolveStoredResult(outcome);
      this.devLinkLastResult = outcome.result;
      if (outcome.t === 'failed') throw new Error(outcome.message || 'robot program failed');
      return outcome.result;
    } finally {
      this.devLinkBusyCount = Math.max(0, this.devLinkBusyCount - 1);
      UI ['progress'].end();
      UI ['workspace'].runButton.status = true;
      UI ['workspace'].runButton.dom.className = 'icon';
      UI ['workspace'].toolbarButton.className = 'icon medium';
    }
  }

  async runAgainWithLastResult(source) {
    return this.runProgram(source, this.devLinkLastResult);
  }

  async stopProgram() {
    if (this.devLink) {
      try {
        return await this.devLinkWrite({op: 'stop'});
      } finally {
        // A stop acknowledgement is enough to return control to the user.
        // Do not depend on a later terminal/result notification: there may
        // have been no program running, so no notification would arrive.
        this.devLinkIdleUi();
      }
    }
  }

  /**Show an attached DevLink robot as connected but not running.*/
  devLinkIdleUi() {
    const workspace = UI ['workspace'];
    workspace.channel_connect.className = '';
    workspace.runButton.status = true;
    workspace.runButton.dom.className = 'icon';
    workspace.toolbarButton.className = 'icon medium';
    workspace.connectButton.className = 'icon on';
    workspace.term.className = 'on';
  }

	/**
   * Connect using webbluetooth protocol, will ask user permission for the bluetooth device.
   */
  connect () {
    if (typeof navigator.bluetooth == "undefined") {
      UI ['notify'].send(MSG['notAvailableFlag'].replaceAll('$1', 'WebBluetooth API'));
      term.write(MSG['notAvailableFlag'].replaceAll('$1', 'WebBluetooth API'));
      return;
    }
      navigator.bluetooth.requestDevice({
        //filters: [{services: []}]
        optionalServices: [webbluetooth.ServiceUUID],
        acceptAllDevices: true
      })
      .then(device => {
        UI ['workspace'].connecting ();
        this.device = device; //check
        this.devLink = device.name === 'MPY-DEV-C3';
        UI ['notify'].log('Found ' + device.name);
        UI ['notify'].log('Connecting to GATT Server...');
        this.device.addEventListener('gattserverdisconnected', this.disconnect.bind(this));
        return device.gatt.connect();
      })
      .then(server => {
        UI ['notify'].log('Locate NUS service');
        return server.getPrimaryService(webbluetooth.ServiceUUID);
      }).then(service => {
        this.nusService = service;
        UI ['notify'].log('Found NUS service: ' + service.uuid);
      })
      .then(() => {
        UI ['notify'].log('Locate RX characteristic');
        return this.nusService.getCharacteristic(webbluetooth.RXUUID);
      })
      .then(characteristic => {
        this.rxCharacteristic = characteristic;
        UI ['notify'].log('Found RX characteristic');
      })
      .then(() => {
        UI ['notify'].log('Locate TX characteristic');
        return this.nusService.getCharacteristic(webbluetooth.TXUUID);
      })
      .then(characteristic => {
        this.txCharacteristic = characteristic;
        UI ['notify'].log('Found TX characteristic');
      })
      .then(() => {
        UI ['notify'].log('Enable notifications');
        return this.txCharacteristic.startNotifications();
      })
      .then(() => {
        UI ['notify'].log('Notifications started');
        this.txCharacteristic.addEventListener('characteristicvaluechanged', this.handleNotifications.bind(this));
        term.on();
        term.write('\x1b[31mConnected using Web Bluetooth API'
                   + (this.devLink ? ' (MicroPython DevLink)' : '')
                   + ' !\x1b[m\r\n');
        this.connected = true;
        if (this.devLink) {
          clearInterval(this.devLinkHeartbeat);
          this.devLinkHeartbeat = setInterval(
            this.devLinkHeartbeatTick.bind(this), 10000);
        }
        if (!this.devLink) mux.bufferPush ('\r');
        // Legacy Nordic-UART boards expose a REPL and remain in the
        // receiving state after connection. DevLink is request/response:
        // a fresh, idle connection must show Run, not Stop.
        if (this.devLink)
          this.devLinkIdleUi();
        else if (UI ['workspace'].runButton.status == true)
          UI ['workspace'].receiving ();
        this.watcher = setInterval(this.watch.bind(this), 50);
      }).catch(error => {
        UI ['notify'].log(error);
        term.write('' + error);
        UI ['workspace'].runAbort();
        if(this.device && this.device.gatt.connected)
          this.device.gatt.disconnect();
      });
  }
  /**
   * Disconnect device connected with webbluetooth protocol.
   */
  disconnect () {
    const disconnectError = new Error('Bluetooth robot disconnected');
    this.devLinkWaiters.splice(0).forEach(waiter => {
      clearTimeout(waiter.timer);
      waiter.reject(disconnectError);
    });
    this.devLinkTerminalWaiters.splice(0).forEach(waiter =>
      { clearTimeout(waiter.timer); waiter.reject(disconnectError); });
    if (!this.device) {
      UI ['notify'].log('No Bluetooth Device connected...');
    } else {
      UI ['notify'].log('Disconnecting from Bluetooth Device...');
      if (this.device.gatt.connected) {
        this.device.gatt.disconnect();
      } else
        UI ['notify'].log('> Bluetooth Device is already disconnected');
    }
    term.off();
    this.device = undefined;
    this.nusService = undefined;
    this.txCharacteristic = undefined;
    this.rxCharacteristic = undefined;
    this.connected = false;
    this.devLink = false;
    this.devLinkLineBuffer = '';
    this.devLinkHeartbeatPending = false;
    this.devLinkBusyCount = 0;

    clearInterval(this.watcher);
    clearInterval(this.devLinkHeartbeat);
    this.devLinkHeartbeat = undefined;
    UI ['workspace'].runAbort();
  }

	/**
   * Handles data received via webbluetooth
   * @param {string} event - data received via webbluetooth
   */
  handleNotifications(event) {
    let value = event.target.value;
    // Convert raw data bytes to character values and use these to
    // construct a string.
    let chunk = "";
    for (let i = 0; i < value.byteLength; i++) {
      chunk += String.fromCharCode(value.getUint8(i));
    }
    if (this.devLink) {
      this.devLinkLineBuffer += chunk;
      let newline;
      while ((newline = this.devLinkLineBuffer.indexOf('\n')) >= 0) {
        const line = this.devLinkLineBuffer.slice(0, newline);
        this.devLinkLineBuffer = this.devLinkLineBuffer.slice(newline + 1);
        if (!line) continue;
        let message;
        try {
          message = JSON.parse(line);
        } catch (error) {
          term.write(line + '\r\n');
          continue;
        }
        if (message.t === 'log') {
          const text = String(message.v || '') + (message.end === undefined ? '\n' : message.end);
          term.write(text.replace(/\n/g, '\r\n'));
          Files.received_string = Files.received_string.concat(text);
          Tool.bipesVerify();
        } else if (message.t === 'event') {
          term.write('[data] ' + JSON.stringify(message.v) + '\r\n');
        } else if (message.t === 'started') {
          term.write('[robot started]\r\n');
        } else if (['done', 'failed', 'cancelled'].includes(message.t)) {
          this.devLinkLastResult = message.result;
          term.write(message.t === 'done'
            ? '[robot finished] ' + JSON.stringify(message.result) + '\r\n'
            : '[robot ' + message.t + '] ' + (message.message || '') + '\r\n');
          const terminals = this.devLinkTerminalWaiters.splice(0);
          terminals.forEach(waiter => {
            clearTimeout(waiter.timer);
            waiter.resolve(message);
          });
        }
        const waiterIndex = this.devLinkWaiters.findIndex(waiter =>
          waiter.operation === message.op
          && (message.t === 'error' || waiter.type === message.t));
        if (waiterIndex >= 0) {
          const waiter = this.devLinkWaiters.splice(waiterIndex, 1)[0];
          clearTimeout(waiter.timer);
          if (message.t === 'error') waiter.reject(new Error(message.message));
          else waiter.resolve(message);
        }
      }
      return;
    }
    term.write(chunk);
    Tool.bipesVerify ();
    //data comes in chunks, keep last 4 chars to check MicroPython REPL string
    this.last4chars = this.last4chars.concat(chunk.substr(-4,4)).substr(-4,4)
    if (this.last4chars.includes(">>> ")) {
      UI ['workspace'].runButton.status = true;
      UI ['workspace'].runButton.dom.className = 'icon';
      UI ['workspace'].toolbarButton.className = 'icon medium';
      if (this.completeBufferCallback.length > 0) {
        try {
          this.completeBufferCallback [0] ();
        } catch (e) {
          UI ['notify'].log(e);
        }
        this.completeBufferCallback.shift ();
      }
    } else if (UI ['workspace'].runButton.status == true) {
      UI ['workspace'].receiving ();
    }
    Files.received_string = Files.received_string.concat(chunk);
  }
}
