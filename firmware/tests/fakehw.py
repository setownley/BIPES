"""Minimal CPython stand-ins for the MicroPython modules robot.py imports.

Records Timer construction/init/deinit so a test can assert whether Timer 0 was
ever created. The I2C bus models a board with the OLED fitted but no VL53L0X:
reads to 0x29 raise OSError (ENODEV), which is robot.py's documented fail-soft
path for boards without the side sensor.
"""
import sys, types

TIMER_EVENTS = []          # ('construct'|'init'|'deinit', timer_id)

class Pin:
    OUT = 'OUT'; IN = 'IN'; PULL_UP = 'PULL_UP'
    def __init__(self, *a, **k): self._v = 0
    def value(self, *a):
        if a: self._v = a[0]
        return self._v

class I2C:
    TOF_ADDR = 0x29
    def __init__(self, *a, **k): pass
    def scan(self): return [0x3C]
    def _guard(self, addr):
        if addr == self.TOF_ADDR: raise OSError(19, 'ENODEV')
    def writeto(self, addr, *a, **k): self._guard(addr)
    def readfrom(self, addr, *a, **k): self._guard(addr); return bytes(1)
    def readfrom_mem(self, addr, *a, **k): self._guard(addr); return bytes(1)
    def writeto_mem(self, addr, *a, **k): self._guard(addr)

class Timer:
    PERIODIC = 'PERIODIC'; ONE_SHOT = 'ONE_SHOT'
    def __init__(self, tid, *a, **k):
        self.tid = tid; TIMER_EVENTS.append(('construct', tid))
    def init(self, **k): TIMER_EVENTS.append(('init', self.tid))
    def deinit(self):    TIMER_EVENTS.append(('deinit', self.tid))

class PWM:
    def __init__(self, *a, **k): self._d = 0
    def freq(self, *a): return 1000
    def duty(self, *a):
        if a: self._d = a[0]
        return self._d
    def deinit(self): pass

class ADC:
    ATTN_11DB = 'ATTN_11DB'; WIDTH_12BIT = 'WIDTH_12BIT'
    def __init__(self, *a, **k): pass
    def atten(self, *a): pass
    def width(self, *a): pass
    def read(self): return 0

def time_pulse_us(*a, **k): return -2

class _SSD1306_I2C:
    def __init__(self, *a, **k): self.paints = 0
    def fill(self, *a): pass
    def text(self, *a): pass
    def show(self): self.paints += 1
    def poweroff(self): pass

def _patch_time():
    import time as _t
    if not hasattr(_t, 'sleep_ms'):
        _t.sleep_ms = lambda ms: None          # no real delays in tests
        _t.sleep_us = lambda us: None
        _t.ticks_ms = lambda: int(_t.monotonic() * 1000)
        _t.ticks_us = lambda: int(_t.monotonic() * 1000000)
        _t.ticks_diff = lambda a, b: a - b
        _t.ticks_add = lambda a, b: a + b
    sys.modules['utime'] = _t

def install():
    _patch_time()
    import builtins as _b
    _b.const = lambda x: x      # MicroPython compiler builtin
    m = types.ModuleType('machine')
    for n in ('Pin', 'I2C', 'Timer', 'PWM', 'ADC', 'time_pulse_us'):
        setattr(m, n, globals()[n])
    sys.modules['machine'] = m
    s = types.ModuleType('ssd1306')
    s.SSD1306_I2C = _SSD1306_I2C
    sys.modules['ssd1306'] = s
