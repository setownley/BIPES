"""Verifies the robot_settings.txt OS_TIMER mechanism in firmware/robot.py.

Run from the repo root:   python firmware/tests/test_os_timer.py
Exits non-zero on any failure. Hardware is stubbed (see fakehw.py), so this
checks the settings/startup/teardown logic only - it is not a substitute for a
bench run.

The module is imported with the CWD set to a scratch directory, because
robot.py opens robot_settings.txt relative to the working directory (on the
board that is the flash root).
"""
import sys, os, importlib, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)                       # firmware/
sys.path.insert(0, HERE)
sys.path.insert(0, FW)
import fakehw

SETTINGS = "robot_settings.txt"

fails = []
def check(label, cond, detail=''):
    print(('  PASS  ' if cond else '  FAIL  ') + label + (('  <- ' + detail) if detail and not cond else ''))
    if not cond:
        fails.append(label)

def write_settings(text):
    with open(SETTINGS, 'w') as f:
        f.write(text)

def clear_settings():
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)

def load_robot():
    """Fresh import, as a power-up would do."""
    sys.modules.pop('robot', None)
    fakehw.TIMER_EVENTS.clear()
    return importlib.import_module('robot')

def constructs():
    return [e for e in fakehw.TIMER_EVENTS if e[0] == 'construct']
def inits():
    return [e for e in fakehw.TIMER_EVENTS if e[0] == 'init']
def deinits():
    return [e for e in fakehw.TIMER_EVENTS if e[0] == 'deinit']

fakehw.install()
scratch = tempfile.mkdtemp(prefix='bipes_robot_test_')
os.chdir(scratch)

# ------------------------------------------------------------------ import
print('Import with no settings file (must behave like the pre-feature OS)')
clear_settings()
r = load_robot()
check('OS_TIMER defaults True', r.OS_TIMER is True, repr(r.OS_TIMER))
check('Timer 0 constructed', ('construct', 0) in fakehw.TIMER_EVENTS)
check('Timer 0 started', ('init', 0) in fakehw.TIMER_EVENTS)
check('_tim is live', r._tim is not None)
check('VERSION bumped to 0.5.8', r.VERSION == '0.5.8', r.VERSION)
check('SETTINGS_FILE name', r.SETTINGS_FILE == 'robot_settings.txt', r.SETTINGS_FILE)

print('Import with OS_TIMER=1')
write_settings('OS_TIMER=1\n')
r = load_robot()
check('OS_TIMER True', r.OS_TIMER is True, repr(r.OS_TIMER))
check('Timer 0 started', ('init', 0) in fakehw.TIMER_EVENTS)

print('Import with OS_TIMER=0 (electronics mode)')
write_settings('OS_TIMER=0\n')
r = load_robot()
check('OS_TIMER False', r.OS_TIMER is False, repr(r.OS_TIMER))
check('Timer NEVER constructed', constructs() == [], repr(fakehw.TIMER_EVENTS))
check('no timer init at all', inits() == [], repr(fakehw.TIMER_EVENTS))
check('_tim is None', r._tim is None)
check('public API intact', all(hasattr(r, n) for n in
      ('forward', 'stop', 'distance_mm', 'show', 'os_timer', 'apply_settings')))

print('Malformed / hostile settings files all fall back to timer ON')
for bad in ('OS_TIMER=banana\n', 'OS_TIMER=\n', '\n', 'garbage\n',
            'NOT_OS_TIMER=0\n', 'OS_TIMER0\n', '', 'OS_TIMER = 0\n'):
    write_settings(bad)
    r = load_robot()
    check('  %-22r -> timer ON' % bad, r.OS_TIMER is True and ('init', 0) in fakehw.TIMER_EVENTS)

print('Unreadable settings file falls back to timer ON')
clear_settings()
os.mkdir(SETTINGS)               # a directory where a file is expected
try:
    r = load_robot()
    check('directory in place of file -> timer ON',
          r.OS_TIMER is True and ('init', 0) in fakehw.TIMER_EVENTS)
finally:
    os.rmdir(SETTINGS)

# ------------------------------------------------- apply_settings live toggle
print('apply_settings() live toggle, with the module already imported')
write_settings('OS_TIMER=1\n')
r = load_robot()
check('starts with the timer running', r._tim is not None)

fakehw.TIMER_EVENTS.clear()
write_settings('OS_TIMER=0\n')
r.apply_settings()
check('ON -> OFF deinits Timer 0', deinits() == [('deinit', 0)], repr(fakehw.TIMER_EVENTS))
check('ON -> OFF clears _tim', r._tim is None)
check('ON -> OFF updates OS_TIMER', r.OS_TIMER is False)

fakehw.TIMER_EVENTS.clear()
r.apply_settings()
check('OFF -> OFF is idempotent (no events)', fakehw.TIMER_EVENTS == [], repr(fakehw.TIMER_EVENTS))
check('OFF -> OFF keeps _tim None', r._tim is None)

fakehw.TIMER_EVENTS.clear()
write_settings('OS_TIMER=1\n')
r.apply_settings()
check('OFF -> ON constructs Timer 0', constructs() == [('construct', 0)], repr(fakehw.TIMER_EVENTS))
check('OFF -> ON inits Timer 0', inits() == [('init', 0)], repr(fakehw.TIMER_EVENTS))
check('OFF -> ON updates OS_TIMER', r.OS_TIMER is True)

fakehw.TIMER_EVENTS.clear()
r.apply_settings()
check('ON -> ON is idempotent (no events)', fakehw.TIMER_EVENTS == [], repr(fakehw.TIMER_EVENTS))
check('ON -> ON keeps one live timer', r._tim is not None)

check('apply_settings returns the applied state', r.apply_settings() is True)

# ------------------------------------------------------------- os_timer()
print('os_timer() live override shares the same helpers and leaves the file alone')
write_settings('OS_TIMER=1\n')
r = load_robot()
fakehw.TIMER_EVENTS.clear()
r.os_timer(False)
check('os_timer(False) deinits', deinits() == [('deinit', 0)] and r._tim is None)
r.os_timer(False)
check('os_timer(False) idempotent', deinits() == [('deinit', 0)])
r.os_timer(True)
check('os_timer(True) restarts', ('init', 0) in fakehw.TIMER_EVENTS and r._tim is not None)
with open(SETTINGS) as f:
    check('os_timer() did NOT rewrite the settings file', f.read().strip() == 'OS_TIMER=1')

# -------------------------------------------------------------- shutdown
print('shutdown()')
write_settings('OS_TIMER=1\n')
r = load_robot()
r.shutdown()
check('deinits a live timer', ('deinit', 0) in fakehw.TIMER_EVENTS)
check('leaves _tim None', r._tim is None)
write_settings('OS_TIMER=0\n')
r = load_robot()
try:
    r.shutdown()
    check('safe when the timer never existed', True)
except Exception as e:
    check('safe when the timer never existed', False, repr(e))

# ------------------------------------------------- no builtins mechanism left
print('Previous builtins mechanism is gone')
src = open(os.path.join(FW, 'robot.py'), encoding='utf-8').read()
check('robot.py has no _BIPES_OS_TIMER', '_BIPES_OS_TIMER' not in src)
check('robot.py imports no builtins', 'import builtins' not in src)

os.chdir(HERE)
shutil.rmtree(scratch, ignore_errors=True)
print()
print('ALL PASS' if not fails else 'FAILURES: ' + repr(fails))
sys.exit(1 if fails else 0)
