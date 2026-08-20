"""Verifies the OS_TIMER startup flag in firmware/robot.py.

Run from the repo root:   python firmware/tests/test_os_timer.py
Exits non-zero on any failure. Hardware is stubbed (see fakehw.py), so this
checks the startup/teardown logic only - it is not a substitute for a bench run.

Test 1 - backward compatibility: no flag set => Timer 0 created and started.
Test 2 - electronics mode: builtins._BIPES_OS_TIMER = False => Timer 0 never
         constructed, so nothing polls the ultrasonic/QRE/VL53L0X or repaints
         the OLED in the background.
"""
import sys, os, builtins, importlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakehw

FW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # firmware/
sys.path.insert(0, FW)

def load_robot():
    for m in ('robot',):
        sys.modules.pop(m, None)
    fakehw.TIMER_EVENTS.clear()
    return importlib.import_module('robot')

fakehw.install()
fails = []
def check(label, cond, detail=''):
    print(('  PASS  ' if cond else '  FAIL  ') + label + (('  <- ' + detail) if detail and not cond else ''))
    if not cond: fails.append(label)

# ---------------------------------------------------------------- Test 1
print('Test 1 - backward compatibility (no flag / flag True)')
if hasattr(builtins, '_BIPES_OS_TIMER'): del builtins._BIPES_OS_TIMER
r = load_robot()
ev = list(fakehw.TIMER_EVENTS)
check('OS_TIMER defaults to True', r.OS_TIMER is True, repr(r.OS_TIMER))
check('Timer(0) constructed', ('construct', 0) in ev, repr(ev))
check('Timer 0 .init() called', ('init', 0) in ev, repr(ev))
check('_tim is a live Timer', r._tim is not None)
check('VERSION bumped', r.VERSION == '0.5.7', r.VERSION)
r.shutdown()
check('shutdown() deinits a live timer', ('deinit', 0) in fakehw.TIMER_EVENTS)

# explicit True behaves identically
builtins._BIPES_OS_TIMER = True
r = load_robot()
check('explicit flag True still starts Timer 0', ('init', 0) in fakehw.TIMER_EVENTS)

# ---------------------------------------------------------------- Test 2
print('Test 2 - electronics mode (flag False before import)')
builtins._BIPES_OS_TIMER = False
r = load_robot()
ev = list(fakehw.TIMER_EVENTS)
check('OS_TIMER is False', r.OS_TIMER is False, repr(r.OS_TIMER))
check('Timer NEVER constructed', all(e[0] != 'construct' for e in ev), repr(ev))
check('no .init() on any timer', all(e[0] != 'init' for e in ev), repr(ev))
check('_tim is None', r._tim is None)
check('robot module still usable (public API present)',
      all(hasattr(r, n) for n in ('forward','stop','distance_mm','show','os_timer')))
try:
    r.shutdown()
    check('shutdown() safe when timer was never created', True)
except Exception as e:
    check('shutdown() safe when timer was never created', False, repr(e))

# ---------------------------------------------------------------- runtime toggle
print('Runtime toggle via robot.os_timer() (the IDE Run path)')
r = load_robot()                      # still flag False -> no timer
check('starts with no timer', r._tim is None)
r.os_timer(True)
check('os_timer(True) creates and starts Timer 0',
      ('construct', 0) in fakehw.TIMER_EVENTS and ('init', 0) in fakehw.TIMER_EVENTS)
r.os_timer(True)
check('os_timer(True) is idempotent (no second Timer)',
      [e for e in fakehw.TIMER_EVENTS if e[0] == 'construct'].count(('construct', 0)) == 1,
      repr(fakehw.TIMER_EVENTS))
r.os_timer(False)
check('os_timer(False) deinits and clears', ('deinit', 0) in fakehw.TIMER_EVENTS and r._tim is None)
r.os_timer(False)
check('os_timer(False) idempotent',
      [e for e in fakehw.TIMER_EVENTS if e[0] == 'deinit'].count(('deinit', 0)) == 1)

del builtins._BIPES_OS_TIMER
print()
print(('ALL PASS' if not fails else 'FAILURES: ' + repr(fails)))
sys.exit(1 if fails else 0)
