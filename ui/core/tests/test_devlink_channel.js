/* Node-only protocol regression test for the browser DevLink channel. */
const assert = require('assert');
const crypto = require('crypto').webcrypto;
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const channelPath = path.join(__dirname, '..', 'channel.js');
const source = fs.readFileSync(channelPath, 'utf8')
  + '\nglobalThis.TestWebBluetooth = webbluetooth;';
const terminal = [];
const context = {
  TextEncoder, TextDecoder, Uint8Array, ArrayBuffer, Promise, Error,
  JSON, String, Number, Array, Math, btoa, atob, crypto,
  setTimeout, clearTimeout, setInterval, clearInterval,
  window: {location: {origin: 'http://127.0.0.1', protocol: 'http:'}},
  UI: {
    progress: {start() {}, remain() {}, end() {}},
    workspace: {
      receiving() {}, runAbort() {},
      runButton: {status: true, dom: {className: ''}},
      toolbarButton: {className: ''},
      channel_connect: {className: ''},
      connectButton: {className: ''},
      term: {className: ''}
    },
    notify: {log() {}, send() {}}
  },
  Files: {received_string: ''},
  files: {update_file_status() {}},
  Tool: {bipesVerify() {}},
  term: {write(value) { terminal.push(value); }, on() {}, off() {}},
  MSG: {}, navigator: {}
};
vm.createContext(context);
vm.runInContext(source, context, {filename: channelPath});

const link = new context.TestWebBluetooth();
link.devLink = true;
link.devLinkRunTimeoutMs = 15;
link.devLinkRecoveryDelayMs = 1;
link.devLinkCommandTimeoutMs = 15;
link.devLinkUploadRetryDelayMs = 1;
link.devLinkMotorSafeDelayMs = 1;
link.devLinkCalibrationSafeDelayMs = 1;
const commands = [];
let runId = 0;
let dropDone = false;
let retainedOutcome = null;
let corruptNextRetained = false;
let dropChunkAck = false;
let droppedChunkAck = false;
const boardFile = new TextEncoder().encode('calibration ✓\n'.repeat(35));
let corruptFileHash = false;

function notification(message, splitAt) {
  const bytes = new TextEncoder().encode(JSON.stringify(message) + '\n');
  const pieces = splitAt ? [bytes.slice(0, splitAt), bytes.slice(splitAt)] : [bytes];
  for (const piece of pieces) {
    link.handleNotifications({target: {value: new DataView(
      piece.buffer, piece.byteOffset, piece.byteLength)}});
  }
}

link.rxCharacteristic = {
  writeValueWithResponse(bytes) {
    const command = JSON.parse(new TextDecoder().decode(bytes));
    commands.push(command);
    queueMicrotask(() => {
      if (command.op === 'chunk' && dropChunkAck && !droppedChunkAck) {
        // Simulate bytes reaching the board while the ACK notification is
        // lost. The next begin must safely restart the atomic upload.
        droppedChunkAck = true;
        return;
      }
      notification({t: 'ack', op: command.op, n: command.n,
        run_id: command.op === 'run' ? runId + 1 : undefined}, 4);
      if (command.op === 'run') {
        runId += 1;
        const id = runId;
        retainedOutcome = {t: 'done', run_id: id, result: {next: id + 1}};
        if (!command.quiet) {
          notification({t: 'started', run_id: id});
          notification({t: 'log', v: 'hello', end: '\n'}, 7);
          if (!dropDone) notification(retainedOutcome, 9);
        }
      } else if (command.op === 'result') {
        let outcome = retainedOutcome;
        if (corruptNextRetained) {
          corruptNextRetained = false;
          outcome = {t: 'done', run_id: runId, result: {next: 999}};
        }
        notification({t: 'result', op: 'result', run_id: runId,
          running: false, outcome}, 11);
      } else if (command.op === 'status') {
        notification({t: 'status', op: 'status', run_id: runId,
          running: false, free_memory: 70000}, 8);
      } else if (command.op === 'files') {
        notification({t: 'files', op: 'files',
          items: [{name: 'cal_log.txt', size: boardFile.length}]}, 8);
      } else if (command.op === 'file_info') {
        crypto.subtle.digest('SHA-256', boardFile).then(digest => {
          let sha = Array.from(new Uint8Array(digest))
            .map(value => value.toString(16).padStart(2, '0')).join('');
          if (corruptFileHash) sha = '0'.repeat(64);
          notification({t: 'file_info', op: 'file_info', name: command.name,
            size: boardFile.length, sha256: sha}, 13);
        });
      } else if (command.op === 'file_read') {
        const block = boardFile.slice(command.offset, command.offset + command.length);
        notification({t: 'file', op: 'file_read', name: command.name,
          offset: command.offset, data: link.devLinkBase64(block),
          eof: command.offset + block.length >= boardFile.length,
          size: boardFile.length}, 10);
      }
    });
    return Promise.resolve();
  }
};

(async () => {
  // Connecting to an idle DevLink robot must show Run. This used to call
  // the legacy REPL transition and strand the UI on Stop.
  context.UI.workspace.runButton.status = false;
  context.UI.workspace.runButton.dom.className = 'icon on';
  link.devLinkIdleUi();
  assert.strictEqual(context.UI.workspace.runButton.status, true);
  assert.strictEqual(context.UI.workspace.runButton.dom.className, 'icon');
  assert.strictEqual(context.UI.workspace.connectButton.className, 'icon on');

  const longSource = 'print("héllo")\n' + '#'.repeat(420);
  const result = await link.runProgram(longSource, {previous: 1});
  assert.deepStrictEqual(result, {next: 2});
  assert.strictEqual(commands[0].op, 'begin');
  assert.strictEqual(commands[0].size, new TextEncoder().encode(longSource).length);
  assert(commands.filter(command => command.op === 'chunk').length > 1);
  assert.deepStrictEqual(commands.filter(command => command.op === 'chunk')
    .map(command => command.n), [0, 1, 2, 3]);
  assert(commands.some(command => command.op === 'input'));
  assert.strictEqual(commands[commands.length - 1].op, 'run');
  assert.deepStrictEqual(link.devLinkLastResult, {next: 2});
  assert(terminal.join('').includes('hello'));

  commands.length = 0;
  corruptNextRetained = true;
  const motorSafe = await link.runProgram(
    "import robot\nrobot.nudge('left', 10)\n");
  const motorRun = commands.find(command => command.op === 'run');
  assert.strictEqual(motorRun.quiet, true);
  assert(commands.some(command => command.op === 'result'));
  assert(commands.filter(command => command.op === 'result').length >= 3);
  assert.deepStrictEqual(motorSafe, {next: 3});
  assert(terminal.join('').includes('motor-safe run'));

  commands.length = 0;
  await link.runProgram('print("plain")\n');
  const inputCommand = commands.find(command => command.op === 'input');
  const decodedInput = Buffer.from(inputCommand.d, 'base64').toString('utf8');
  assert.strictEqual(decodedInput, 'null');

  commands.length = 0;
  dropChunkAck = true;
  const retried = await link.runProgram('print("retry")\n' + '#'.repeat(150));
  assert.deepStrictEqual(retried, {next: 5});
  assert.strictEqual(commands.filter(command => command.op === 'begin').length, 2);
  assert.strictEqual(droppedChunkAck, true);
  dropChunkAck = false;

  // Lose the entire terminal notification. The browser must ask the board
  // for its retained result instead of leaving the Run button hung forever.
  commands.length = 0;
  dropDone = true;
  const recovered = await link.runProgram('print("recover")\n', {previous: 2});
  assert.deepStrictEqual(recovered, {next: 6});
  assert(commands.some(command => command.op === 'result'));
  assert(terminal.join('').includes('recovering final robot result'));
  assert.deepStrictEqual(link.devLinkLastResult, {next: 6});

  const listed = await link.devLinkListFiles();
  assert.strictEqual(listed[0].name, 'cal_log.txt');
  const downloaded = await link.devLinkReadFile('cal_log.txt');
  assert.deepStrictEqual(Array.from(downloaded), Array.from(boardFile));
  assert(commands.filter(command => command.op === 'file_read').length > 1);
  corruptFileHash = true;
  await assert.rejects(link.devLinkReadFile('cal_log.txt'), /SHA-256/);
  corruptFileHash = false;

  const largeResult = {samples: Array.from({length: 180}, (_, index) => index)};
  const largeBody = new TextEncoder().encode(JSON.stringify(largeResult));
  const largeDigest = await crypto.subtle.digest('SHA-256', largeBody);
  const largeHash = Array.from(new Uint8Array(largeDigest))
    .map(value => value.toString(16).padStart(2, '0')).join('');
  const originalReadFile = link.devLinkReadFile.bind(link);
  link.devLinkReadFile = async name => {
    assert.strictEqual(name, 'devlink_result.json');
    return largeBody;
  };
  const resolved = await link.devLinkResolveStoredResult({
    t: 'done', run_id: 99, result: {
      stored_file: 'devlink_result.json', bytes: largeBody.length,
      sha256: largeHash
    }
  });
  assert.deepStrictEqual(resolved.result, largeResult);
  await assert.rejects(link.devLinkResolveStoredResult({
    t: 'done', run_id: 99, result: {
      stored_file: 'devlink_result.json', bytes: largeBody.length,
      sha256: '0'.repeat(64)
    }
  }), /manifest/);
  link.devLinkReadFile = originalReadFile;

  const pending = link.devLinkWrite({op: 'status'}, 'status');
  notification({t: 'error', op: 'status', message: 'expected'});
  await assert.rejects(pending, /expected/);

  // An idle BIPES connection must stay active beyond the board's 30-second
  // stale-central cutoff, but no heartbeat may interrupt a motor-safe run or
  // a checksummed file transfer.
  commands.length = 0;
  link.connected = true;
  link.devLinkHeartbeatTick();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.strictEqual(commands.filter(command => command.op === 'status').length, 1);
  commands.length = 0;
  link.devLinkBusyCount = 1;
  link.devLinkHeartbeatTick();
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.strictEqual(commands.length, 0);
  link.devLinkBusyCount = 0;
  link.connected = false;

  console.log('ALL PASS');
})().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
