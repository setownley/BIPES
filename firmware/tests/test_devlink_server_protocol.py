"""Host-side checks for the MicroPython DevLink board supervisor."""

import asyncio as cpython_asyncio
import base64
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import types

import gc

if not hasattr(gc, "mem_free"):
    gc.mem_free = lambda: 1_000_000


HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_PATH = os.path.join(os.path.dirname(HERE), "devlink_server.py")


class FakeBLE:
    next_read = b""

    def __init__(self):
        self.advertisements = 0
        self.advertisement_calls = []
        self.disconnections = []

    def active(self, value):
        pass

    def config(self, **kwargs):
        pass

    def gatts_register_services(self, services):
        return ((1, 2),)

    def gatts_set_buffer(self, *args):
        pass

    def irq(self, callback):
        self.callback = callback

    def gap_advertise(self, *args, **kwargs):
        self.advertisements += 1
        self.advertisement_calls.append((args, kwargs))

    def gap_disconnect(self, connection):
        self.disconnections.append(connection)

    def gatts_read(self, handle):
        return self.next_read


class FakeWDT:
    instances = []

    def __init__(self, timeout):
        self.timeout = timeout
        self.feeds = 0
        self.instances.append(self)

    def feed(self):
        self.feeds += 1


bluetooth = types.ModuleType("bluetooth")
class FakeUUID:
    def __init__(self, value):
        self.value = value

    def __bytes__(self):
        # MicroPython exposes the packed 128-bit value through bytes(UUID).
        return bytes(range(16))


bluetooth.UUID = FakeUUID
bluetooth.FLAG_READ = 1
bluetooth.FLAG_NOTIFY = 2
bluetooth.FLAG_WRITE = 4
bluetooth.FLAG_WRITE_NO_RESPONSE = 8
bluetooth.BLE = FakeBLE
sys.modules["bluetooth"] = bluetooth

micropython = types.ModuleType("micropython")
micropython.const = lambda value: value
sys.modules["micropython"] = micropython

uasyncio = types.ModuleType("uasyncio")
uasyncio.CancelledError = cpython_asyncio.CancelledError
uasyncio.create_task = cpython_asyncio.create_task
uasyncio.gather = cpython_asyncio.gather
async def sleep_ms(milliseconds):
    await cpython_asyncio.sleep(milliseconds / 1000)
uasyncio.sleep_ms = sleep_ms
sys.modules["uasyncio"] = uasyncio

machine = types.ModuleType("machine")
machine.WDT = FakeWDT
machine.reset_cause = lambda: 3
sys.modules["machine"] = machine

spec = importlib.util.spec_from_file_location("tested_devlink_server", SERVER_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


async def main():
    with tempfile.TemporaryDirectory(prefix="devlink_server_test_") as scratch:
        module._APP_FILE = os.path.join(scratch, "devlink_app.py")
        module._NEXT_FILE = os.path.join(scratch, "devlink_next.py")
        module._INPUT_FILE = os.path.join(scratch, "devlink_input.json")
        module._RESULT_FILE = os.path.join(scratch, "devlink_result.json")
        module._ROOT = scratch.replace("\\", "/")
        server = module.DevLinkServer()

        _, advertise = server.ble.advertisement_calls[-1]
        adv_data = bytes(advertise["adv_data"])
        resp_data = bytes(advertise["resp_data"])
        assert adv_data[:3] == b"\x02\x01\x06"
        assert adv_data[3:5] == b"\x11\x07"
        assert len(adv_data) == 21
        assert resp_data[1] == 0x09
        assert resp_data[2:] == b"MPY-DEV-C3"

        assert server.watchdog.timeout == 20000
        assert server.watchdog.feeds == 1

        fake_robot = types.ModuleType("robot")
        fake_robot._hold = False
        fake_robot._pwm = {}
        fake_robot.stops = 0
        fake_robot.clears = 0
        fake_robot.sinks = []
        fake_robot.emergency_stop = lambda: setattr(
            fake_robot, "stops", fake_robot.stops + 1)
        fake_robot.clear_abort = lambda: setattr(
            fake_robot, "clears", fake_robot.clears + 1)
        fake_robot.set_log_sink = lambda sink: fake_robot.sinks.append(sink)
        fake_robot.watchdog_feeders = []
        fake_robot.set_watchdog_feed = lambda callback: (
            fake_robot.watchdog_feeders.append(callback)
        )
        sys.modules["robot"] = fake_robot
        server.pending = b'{"op":"status"}'
        server.ble.next_read = b'{"op":"stop"}'
        server._irq(module._IRQ_GATTS_WRITE, (0, server.rx_handle))
        assert fake_robot.stops == 1
        assert server.pending == b'{"op":"stop"}'
        server.pending = None

        server.outbox[:] = [{"t": "log", "v": "stale"}]
        server.pending = b'{"op":"status"}'
        server._irq(module._IRQ_CENTRAL_DISCONNECT, (0,))
        assert server.outbox == []
        assert server.pending is None

        server.outbox.clear()
        await server.handle("status", {})
        assert server.outbox[-1]["watchdog"] is True
        assert server.outbox[-1]["reset_cause"] == 3
        assert server.outbox[-1]["server_version"] == "1.3.7"
        assert server.outbox[-1]["ble_recoveries"] == 0

        advertisements = server.ble.advertisements
        server.connection = None
        server.last_advertise_ms = (
            module._ticks_ms() - module.ADVERTISE_REFRESH_MS
        )
        server._maintain_ble()
        assert server.ble.advertisements == advertisements + 1
        assert server.ble_recoveries == 1

        server.connection = 7
        server.last_activity_ms = module._ticks_ms() - module.CONNECTION_IDLE_MS
        server._maintain_ble()
        assert server.connection is None
        assert server.ble.disconnections == [7]
        assert server.ble_recoveries == 2
        assert server.ble.advertisements >= 2

        source = b'_devlink_result = {"answer": ctx.input["seed"] + 1}\n'
        digest = hashlib.sha256(source).hexdigest()
        await server.handle("begin", {"size": len(source), "sha": digest})
        command = {"n": 0, "d": base64.b64encode(source).decode()}
        await server.handle("chunk", command)
        await server.handle("chunk", command)  # lost-ACK retry
        await server.handle("commit", {})
        assert open(module._APP_FILE, "rb").read() == source
        duplicate_ack = [item for item in server.outbox
                         if item.get("op") == "chunk" and item.get("duplicate")]
        assert len(duplicate_ack) == 1

        server.outbox.clear()
        await server.handle("files", {})
        listing = server.outbox[-1]
        assert listing["t"] == "files"
        assert any(item["name"] == "devlink_app.py" for item in listing["items"])

        server.outbox.clear()
        await server.handle("file_info", {"name": "devlink_app.py"})
        info = server.outbox[-1]
        assert info["size"] == len(source)
        assert info["sha256"] == digest

        server.outbox.clear()
        await server.handle("file_read", {"name": "devlink_app.py",
                                          "offset": 0, "length": 20})
        first = server.outbox[-1]
        assert base64.b64decode(first["data"]) == source[:20]
        assert first["eof"] is False

        try:
            await server.handle("file_info", {"name": "../secret"})
            raise AssertionError("unsafe file name was accepted")
        except ValueError:
            pass

        with open(module._INPUT_FILE, "w") as output:
            json.dump({"seed": 8}, output)
        server.outbox.clear()
        await server._run_program(7)
        assert fake_robot.clears == 1
        assert callable(fake_robot.sinks[0])
        assert fake_robot.sinks[-1] is None
        assert server.last_outcome == {
            "t": "done", "run_id": 7, "result": {"answer": 9}
        }

        large_value = {"samples": list(range(300))}
        with open(module._APP_FILE, "w") as output:
            output.write("_devlink_result = %r\n" % large_value)
        server.outbox.clear()
        await server._run_program(8)
        manifest = server.last_outcome["result"]
        assert manifest["stored_file"] == "devlink_result.json"
        stored_path = os.path.join(scratch, "devlink_result.json")
        stored = open(stored_path, "rb").read()
        assert json.loads(stored) == large_value
        assert manifest["bytes"] == len(stored)
        assert manifest["sha256"] == hashlib.sha256(stored).hexdigest()

        with open(module._APP_FILE, "w") as output:
            output.write('raise RuntimeError("kept failure")\n')
        server.outbox.clear()
        await server._run_program(9)
        assert server.last_outcome["t"] == "failed"
        assert server.last_outcome["run_id"] == 9
        assert "kept failure" in server.last_outcome["message"]

        # Motor-safe runs retain their terminal result but queue no logs,
        # events, started message, or terminal notification for a central
        # which deliberately disconnects after the Run acknowledgement.
        with open(module._APP_FILE, "w") as output:
            output.write(
                'print("hidden")\n'
                'ctx.emit({"phase": "hidden"})\n'
                '_devlink_result = {"quiet": True}\n'
            )
        server.outbox.clear()
        await server._run_program(10, quiet=True)
        assert server.outbox == []
        assert server.last_outcome == {
            "t": "done", "run_id": 10, "result": {"quiet": True}
        }

    print("ALL PASS")


cpython_asyncio.run(main())
