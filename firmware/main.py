import uasyncio as asyncio

# Load the large robot module before allocating the Bluetooth stack. On this
# ESP32-C3, reversing the order can fragment RAM enough for source compilation
# to fail even though the total free-memory figure looks healthy.
try:
    import robot
    robot.apply_settings()
except Exception as exc:
    print("robot dashboard unavailable:", exc)

import devlink_server

asyncio.run(devlink_server.run())
