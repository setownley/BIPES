"""Persistent BLE program runner for ESP32 MicroPython.

Nordic-UART-compatible GATT transport with a JSON command protocol.
This is a development tool, not a security boundary.
"""

import binascii
import bluetooth
import gc
import hashlib
import json
import os
import sys
import time
import uasyncio as asyncio
from micropython import const

try:
    from machine import WDT
except ImportError:  # CPython protocol tests
    WDT = None

try:
    from machine import reset_cause as _machine_reset_cause
except ImportError:  # CPython protocol tests
    _machine_reset_cause = None


VERSION = "1.3.7"
CONNECTION_IDLE_MS = 30_000
ADVERTISE_REFRESH_MS = 120_000
WATCHDOG_TIMEOUT_MS = 20_000


_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)
_IRQ_MTU_EXCHANGED = const(21)

_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (
    bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"),
    bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY,
)
_UART_RX = (
    bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"),
    bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE,
)
_UART_SERVICE = (_UART_UUID, (_UART_TX, _UART_RX))

_APP_FILE = "/devlink_app.py"
_NEXT_FILE = "/devlink_next.py"
_INPUT_FILE = "/devlink_input.json"
_RESULT_FILE = "/devlink_result.json"
_NAME = "MPY-DEV-C3"
_ROOT = "/"


def _board_path(name):
    if not isinstance(name, str) or not name:
        raise ValueError("file name is required")
    if name.startswith("/") or "/" in name or "\\" in name or ".." in name:
        raise ValueError("invalid file name")
    return "/" + name if _ROOT == "/" else _ROOT.rstrip("/") + "/" + name


def _file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as source:
        while True:
            block = source.read(512)
            if not block:
                break
            size += len(block)
            digest.update(block)
    return size, binascii.hexlify(digest.digest()).decode()


def _advertising_payload(service_uuid):
    """Put the service UUID in the primary packet for reliable filtering."""
    payload = bytearray(b"\x02\x01\x06")
    encoded = bytes(service_uuid)
    payload.extend(bytes((len(encoded) + 1, 0x07)))
    payload.extend(encoded)
    return payload


def _scan_response_payload(name):
    """Keep the human-readable name in the separate scan response packet."""
    payload = bytearray()
    encoded = name.encode()
    payload.extend(bytes((len(encoded) + 1, 0x09)))
    payload.extend(encoded)
    return payload


def _ticks_ms():
    try:
        return time.ticks_ms()
    except AttributeError:  # CPython protocol tests
        return int(time.monotonic() * 1000)


def _ticks_diff(newer, older):
    try:
        return time.ticks_diff(newer, older)
    except AttributeError:  # CPython protocol tests
        return newer - older


class Context:
    def __init__(self, server, input_value, quiet=False):
        self._server = server
        self.input = input_value
        self._quiet = bool(quiet)

    def print(self, *values, **kwargs):
        sep = kwargs.get("sep", " ")
        end = kwargs.get("end", "\n")
        value = sep.join(str(v) for v in values)
        if not self._quiet:
            self._server.queue({"t": "log", "v": value, "end": end})

    def emit(self, value):
        if not self._quiet:
            self._server.queue({"t": "event", "v": value})

    def free_memory(self):
        gc.collect()
        return gc.mem_free()

    async def sleep_ms(self, milliseconds):
        await asyncio.sleep_ms(milliseconds)


class _TraceSink:
    def __init__(self, server):
        self.server = server

    def write(self, value):
        if value:
            self.server.queue({"t": "log", "v": value, "end": ""})


class DevLinkServer:
    def __init__(self):
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        self.ble.config(mtu=247)
        # Some ESP32-C3 MicroPython builds do not expose the optional global
        # BLE event-ring size setting. The protocol is ACK-throttled, so the
        # default ring is sufficient when it is unavailable.
        try:
            self.ble.config(rxbuf=2048)
        except ValueError:
            pass
        ((self.tx_handle, self.rx_handle),) = self.ble.gatts_register_services((_UART_SERVICE,))
        self.ble.gatts_set_buffer(self.rx_handle, 512, False)
        self.ble.irq(self._irq)
        self.connection = None
        self.mtu = 23
        self.pending = None
        self.outbox = []
        self.program_task = None
        self.run_id = 0
        self.last_outcome = None
        self.receiving = None
        self.expected_sequence = 0
        self.last_chunk_hash = None
        self.expected_size = 0
        self.expected_hash = ""
        self.last_activity_ms = _ticks_ms()
        self.last_advertise_ms = self.last_activity_ms
        self.ble_recoveries = 0
        self._advertise()
        # Motor PWM has its own independent 8 s deadline in robot.py. Allow
        # transient NimBLE/flash stalls without rebooting the whole runtime.
        self.watchdog = WDT(timeout=WATCHDOG_TIMEOUT_MS) if WDT is not None else None
        self.feed_watchdog()
        # Trusted robot routines feed the same watchdog while they perform a
        # synchronous ramp, brake, or calibration measurement. Arbitrary code
        # which wedges the interpreter does not get that privilege.
        try:
            robot_module = sys.modules.get("robot")
            if robot_module is not None:
                robot_module.set_watchdog_feed(self.feed_watchdog)
        except Exception:
            pass

    def feed_watchdog(self):
        if self.watchdog is not None:
            self.watchdog.feed()

    def _advertise(self):
        self.ble.gap_advertise(
            250_000,
            adv_data=_advertising_payload(_UART_UUID),
            resp_data=_scan_response_payload(_NAME),
        )
        self.last_advertise_ms = _ticks_ms()

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self.connection = data[0]
            self.mtu = 23
            self.last_activity_ms = _ticks_ms()
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self.connection = None
            self.pending = None
            # Notifications have no acknowledgement. Never make a new
            # connection drain stale logs/results from the old one before it
            # can process Stop or Status; terminal state remains queryable.
            self.outbox = []
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            connection, handle = data
            if handle == self.rx_handle:
                self.last_activity_ms = _ticks_ms()
                incoming = bytes(self.ble.gatts_read(self.rx_handle))
                # Uploaded robot programs are intentionally allowed to use
                # synchronous classroom APIs. Do not wait for uasyncio to
                # regain control before killing PWM: latch the exact Stop
                # command at receive time. The normal command loop later
                # cancels the task and sends its acknowledgement.
                if incoming in (b'{"op":"stop"}', b'{"op": "stop"}'):
                    try:
                        robot_module = sys.modules.get("robot")
                        if robot_module is not None:
                            robot_module.emergency_stop()
                    except Exception:
                        pass
                    # Stop has priority over a command which the async loop
                    # has not consumed yet. This also covers a Stop click
                    # immediately after Run.
                    self.pending = incoming
                elif self.pending is None:
                    self.pending = incoming
        elif event == _IRQ_MTU_EXCHANGED:
            connection, mtu = data
            if connection == self.connection:
                self.mtu = mtu

    def queue(self, message):
        # Bound memory if user code logs faster than BLE can transmit.
        if len(self.outbox) < 64:
            self.outbox.append(message)

    def _ack(self, operation, **extra):
        message = {"t": "ack", "op": operation}
        message.update(extra)
        self.queue(message)

    def _error(self, operation, error):
        self.queue({"t": "error", "op": operation, "message": str(error)})

    async def sender(self):
        while True:
            if self.connection is None or not self.outbox:
                await asyncio.sleep_ms(10)
                continue
            message = self.outbox.pop(0)
            try:
                encoded = (json.dumps(message) + "\n").encode()
            except Exception as exc:
                encoded = (json.dumps({"t": "error", "op": "encode", "message": str(exc)}) + "\n").encode()
            size = max(20, self.mtu - 3)
            for offset in range(0, len(encoded), size):
                if self.connection is None:
                    break
                try:
                    self.ble.gatts_notify(self.connection, self.tx_handle, encoded[offset : offset + size])
                    self.last_activity_ms = _ticks_ms()
                except OSError:
                    break
                await asyncio.sleep_ms(8)

    def _maintain_ble(self):
        """Refresh advertising and evict a stale central connection.

        On some ESP32/Windows disconnect races neither side receives the
        disconnect event. The robot OS keeps running, but the board remains
        invisible because it still believes the dead central is connected.
        """
        now = _ticks_ms()
        if self.connection is None:
            # Advertising should be persistent, but NimBLE can occasionally
            # stop emitting after a low-memory/disconnect edge while the
            # Python health loop remains alive. A deliberately slow refresh
            # makes that state self-healing without cycling the board or the
            # computer's Bluetooth radio. The long interval keeps this away
            # from normal Windows discovery/GATT setup.
            if _ticks_diff(now, self.last_advertise_ms) >= ADVERTISE_REFRESH_MS:
                self._advertise()
                self.ble_recoveries += 1
            return
        if _ticks_diff(now, self.last_activity_ms) < CONNECTION_IDLE_MS:
            return
        stale = self.connection
        try:
            self.ble.gap_disconnect(stale)
        except (OSError, AttributeError):
            pass
        # A port may deliver the disconnect IRQ synchronously. Only perform
        # the fallback cleanup if it did not.
        if self.connection == stale:
            self.connection = None
            self.pending = None
            self.outbox = []
            self._advertise()
        self.ble_recoveries += 1

    async def health_loop(self):
        while True:
            self.feed_watchdog()
            self._maintain_ble()
            await asyncio.sleep_ms(1000)

    async def command_loop(self):
        while True:
            self.feed_watchdog()
            if self.pending is None:
                await asyncio.sleep_ms(5)
                continue
            raw = self.pending
            self.pending = None
            operation = "unknown"
            try:
                command = json.loads(raw)
                operation = command.get("op", "unknown")
                await self.handle(operation, command)
            except Exception as exc:
                self._error(operation, exc)

    async def handle(self, operation, command):
        if operation == "begin":
            if self.receiving:
                self.receiving.close()
            try:
                os.remove(_NEXT_FILE)
            except OSError:
                pass
            self.receiving = open(_NEXT_FILE, "wb")
            self.expected_sequence = 0
            self.last_chunk_hash = None
            self.expected_size = int(command["size"])
            self.expected_hash = command["sha"]
            self._ack(operation)
        elif operation == "chunk":
            if self.receiving is None:
                raise ValueError("send begin first")
            sequence = int(command["n"])
            block = binascii.a2b_base64(command["d"])
            block_hash = binascii.hexlify(hashlib.sha256(block).digest()).decode()
            # Notification ACKs are not themselves acknowledged. If the host
            # resends the most recent chunk because its ACK was lost, confirm
            # it without appending the bytes a second time.
            if (
                sequence == self.expected_sequence - 1
                and block_hash == self.last_chunk_hash
            ):
                self._ack(operation, n=sequence, duplicate=True)
                return
            if sequence != self.expected_sequence:
                raise ValueError("expected chunk %d" % self.expected_sequence)
            self.receiving.write(block)
            self.last_chunk_hash = block_hash
            self.expected_sequence += 1
            self._ack(operation, n=sequence)
        elif operation == "commit":
            await self._commit()
            self._ack(operation)
        elif operation == "input":
            raw_input = binascii.a2b_base64(command["d"])
            json.loads(raw_input)
            with open(_INPUT_FILE, "wb") as output:
                output.write(raw_input)
            self._ack(operation)
        elif operation == "run":
            if self.program_task is not None:
                raise ValueError("a program is already running")
            self.run_id += 1
            self.last_outcome = None
            self._ack(operation, run_id=self.run_id)
            quiet = bool(command.get("quiet", False))
            self.program_task = asyncio.create_task(
                self._run_program(self.run_id, quiet)
            )
        elif operation == "stop":
            if self.program_task is not None:
                self.program_task.cancel()
            self._ack(operation)
        elif operation == "status":
            self.queue(
                {
                    "t": "status",
                    "op": operation,
                    "connected": self.connection is not None,
                    "running": self.program_task is not None,
                    "has_program": self._exists(_APP_FILE),
                    "free_memory": gc.mem_free(),
                    "mtu": self.mtu,
                    "run_id": self.run_id,
                    "outcome": self.last_outcome,
                    "watchdog": self.watchdog is not None,
                    "ble_recoveries": self.ble_recoveries,
                    "reset_cause": (
                        _machine_reset_cause()
                        if _machine_reset_cause is not None
                        else None
                    ),
                    "server_version": VERSION,
                }
            )
        elif operation == "result":
            self.queue(
                {
                    "t": "result",
                    "op": operation,
                    "running": self.program_task is not None,
                    "run_id": self.run_id,
                    "outcome": self.last_outcome,
                }
            )
        elif operation == "files":
            items = []
            for name in sorted(os.listdir(_ROOT)):
                try:
                    stat = os.stat(_board_path(name))
                    if stat[0] & 0x4000:  # directory
                        continue
                    items.append({"name": name, "size": stat[6]})
                except OSError:
                    pass
            self.queue({"t": "files", "op": operation, "items": items})
        elif operation == "file_info":
            name = command.get("name")
            size, digest = _file_digest(_board_path(name))
            self.queue({"t": "file_info", "op": operation, "name": name,
                        "size": size, "sha256": digest})
        elif operation == "file_read":
            name = command.get("name")
            path = _board_path(name)
            offset = max(0, int(command.get("offset", 0)))
            length = min(max(1, int(command.get("length", 180))), 180)
            size = os.stat(path)[6]
            with open(path, "rb") as source:
                source.seek(offset)
                block = source.read(length)
            self.queue({"t": "file", "op": operation, "name": name,
                        "offset": offset,
                        "data": binascii.b2a_base64(block).strip().decode(),
                        "eof": offset + len(block) >= size, "size": size})
        else:
            raise ValueError("unknown operation: %s" % operation)

    async def _commit(self):
        if self.receiving is None:
            raise ValueError("no upload in progress")
        self.receiving.close()
        self.receiving = None
        with open(_NEXT_FILE, "rb") as incoming:
            body = incoming.read()
        actual = binascii.hexlify(hashlib.sha256(body).digest()).decode()
        if len(body) != self.expected_size:
            raise ValueError("size mismatch")
        if actual != self.expected_hash:
            raise ValueError("SHA-256 mismatch")
        # Compile before replacing the last known program. Drop each large
        # temporary explicitly so accepting source does not leave the heap
        # fragmented before the next Run compiles it again.
        source = body.decode()
        del body
        gc.collect()
        compiled = compile(source, _APP_FILE, "exec")
        del compiled
        del source
        gc.collect()
        try:
            os.remove(_APP_FILE)
        except OSError:
            pass
        os.rename(_NEXT_FILE, _APP_FILE)

    async def _run_program(self, run_id, quiet=False):
        if not quiet:
            self.queue({"t": "started", "run_id": run_id})
        outcome = None
        try:
            input_value = None
            if self._exists(_INPUT_FILE):
                with open(_INPUT_FILE, "r") as source:
                    input_value = json.load(source)
            gc.collect()
            with open(_APP_FILE, "r") as source:
                code = source.read()
            context = Context(self, input_value, quiet)
            robot_module = sys.modules.get("robot")
            if robot_module is not None:
                set_watchdog_feed = getattr(robot_module,
                                            "set_watchdog_feed", None)
                if set_watchdog_feed is not None:
                    set_watchdog_feed(self.feed_watchdog)
                clear_abort = getattr(robot_module, "clear_abort", None)
                if clear_abort is not None:
                    clear_abort()
                set_log_sink = getattr(robot_module, "set_log_sink", None)
                if set_log_sink is not None:
                    set_log_sink(context.print)
            namespace = {
                "__name__": "__devlink__",
                "ctx": context,
                "print": context.print,
            }
            compiled = compile(code, _APP_FILE, "exec")
            del code
            gc.collect()
            exec(compiled, namespace)
            del compiled
            # Uploaded source may have imported robot for the first time.
            # Bind its trusted waits before invoking an async main entry.
            robot_module = sys.modules.get("robot")
            if robot_module is not None:
                set_watchdog_feed = getattr(robot_module,
                                            "set_watchdog_feed", None)
                if set_watchdog_feed is not None:
                    set_watchdog_feed(self.feed_watchdog)
            # Top-level block programs return data by assigning this name.
            result = namespace.get("_devlink_result")
            entry = namespace.get("main")
            if entry is not None:
                result = entry(context)
                if hasattr(result, "send"):
                    result = await result
            # Large JSON results can monopolise the notification queue on a
            # weak link. Persist them atomically and return a small manifest;
            # the host can resume the checksummed file download in chunks.
            encoded_result = json.dumps(result).encode()
            if len(encoded_result) > 512:
                next_result = _RESULT_FILE + ".next"
                with open(next_result, "wb") as output:
                    output.write(encoded_result)
                try:
                    os.remove(_RESULT_FILE)
                except OSError:
                    pass
                os.rename(next_result, _RESULT_FILE)
                digest = binascii.hexlify(
                    hashlib.sha256(encoded_result).digest()
                ).decode()
                result = {
                    "stored_file": _RESULT_FILE.replace("\\", "/").rsplit("/", 1)[-1],
                    "bytes": len(encoded_result),
                    "sha256": digest,
                }
            outcome = {"t": "done", "run_id": run_id, "result": result}
        except asyncio.CancelledError:
            outcome = {"t": "cancelled", "run_id": run_id}
        except Exception as exc:
            outcome = {"t": "failed", "run_id": run_id, "message": repr(exc)}
            # Preserve the terminal result even if a particular MicroPython
            # build rejects the file-like traceback sink. Previously that
            # secondary failure hid the original exception and reported only
            # "program exited without a result".
            try:
                import io
                trace = io.StringIO()
                sys.print_exception(exc, trace)
                if not quiet:
                    self.queue({"t": "log", "v": trace.getvalue(), "end": ""})
            except Exception as trace_error:
                if not quiet:
                    self.queue({"t": "log", "v": "traceback unavailable: " + repr(trace_error)})
        finally:
            # Robot programs must never leave motor PWM active because their
            # final line was skipped by an exception or cancellation.
            try:
                robot_module = sys.modules.get("robot")
                if robot_module is not None:
                    set_log_sink = getattr(robot_module, "set_log_sink", None)
                    if set_log_sink is not None:
                        set_log_sink(None)
                    motor_pwm = getattr(robot_module, "_pwm", {})
                    if getattr(robot_module, "_hold", False) or any(
                        channel.duty() for channel in motor_pwm.values()
                    ):
                        robot_module.stop()
            except Exception as cleanup_error:
                if not quiet:
                    self.queue({"t": "log", "v": "motor cleanup failed: " + repr(cleanup_error)})
            self.program_task = None
            gc.collect()
            # Retain the terminal state so a dropped notification can be
            # recovered with the result command. Queue it only after safety
            # cleanup so "done" means motors are already stopped.
            if outcome is None:
                outcome = {"t": "failed", "run_id": run_id, "message": "program exited without a result"}
            self.last_outcome = outcome
            if not quiet:
                self.queue(outcome)

    @staticmethod
    def _exists(path):
        try:
            os.stat(path)
            return True
        except OSError:
            return False


async def run():
    server = DevLinkServer()
    await asyncio.gather(server.sender(), server.command_loop(),
                         server.health_loop())
