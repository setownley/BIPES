# boot.py — runs on every power-up and every RESET press, before anything else.
# Purpose: make the RESET button a guaranteed physical kill switch by forcing
# all four DRV8833 inputs low (coast) the moment the chip boots.
#
# Touches ONLY GPIO 3, 4, 7, 10 — none are strapping pins.
# Deliberately does NOT touch GPIO 2 (QRE/strapping), 8 (LED), or 9 (BOOT).

from machine import Pin

for p in (3, 4, 7, 10):
    Pin(p, Pin.OUT).value(0)
