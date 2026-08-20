"""Executes the startup code BIPES generates, against the stubbed firmware.

Run from the repo root:   python firmware/tests/test_generated_startup.py

test_os_timer.py checks robot.py's own logic. This one checks the contract
between BIPES and robot.py: the literal startup snippets that
ui/core/utils.js emits are run here, so a change to either side that breaks
the handshake shows up as a failure.

The snippets below MUST mirror ui/core/utils.js:
  - robot_settings_prelude()  -> IDE_PRELUDE
  - save_main()               -> MAIN_PY_HEAD
"""
import sys, os, importlib, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FW = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, FW)
import fakehw

# --- the exact text ui/core/utils.js produces --------------------------------
def IDE_PRELUDE(value):
    return ("f = open('robot_settings.txt', 'w')\n"
            "f.write('OS_TIMER=%s\\n')\n"
            "f.close()\n"
            "import robot\n"
            "robot.apply_settings()\n" % value)

MAIN_PY_HEAD = "import robot\nrobot.apply_settings()\nrobot.cal_gate()\n"

fails = []
def check(label, cond, detail=''):
    print(('  PASS  ' if cond else '  FAIL  ') + label + (('  <- ' + detail) if detail and not cond else ''))
    if not cond:
        fails.append(label)

def deinits():
    return [e for e in fakehw.TIMER_EVENTS if e[0] == 'deinit']
def inits():
    return [e for e in fakehw.TIMER_EVENTS if e[0] == 'init']

fakehw.install()
scratch = tempfile.mkdtemp(prefix='bipes_gen_test_')
os.chdir(scratch)

print('IDE Run, robot ALREADY imported and ticking, new setting OS_TIMER=0')
with open('robot_settings.txt', 'w') as f:
    f.write('OS_TIMER=1\n')
sys.modules.pop('robot', None)
fakehw.TIMER_EVENTS.clear()
robot = importlib.import_module('robot')          # boot: main.py already ran
check('timer running before the run', robot._tim is not None)

fakehw.TIMER_EVENTS.clear()
ns = {}
exec(IDE_PRELUDE('0'), ns)                        # what BIPES pastes
check('generated prelude stopped the live timer', deinits() == [('deinit', 0)],
      repr(fakehw.TIMER_EVENTS))
check('_tim cleared', robot._tim is None)
check('OS_TIMER now False', robot.OS_TIMER is False)
check('settings file on flash says 0',
      open('robot_settings.txt').read().strip() == 'OS_TIMER=0')
check('`import robot` in the prelude returned the cached module',
      ns['robot'] is robot)

print('IDE Run again, same session, back to OS_TIMER=1')
fakehw.TIMER_EVENTS.clear()
exec(IDE_PRELUDE('1'), {})
check('generated prelude restarted the timer', ('init', 0) in fakehw.TIMER_EVENTS)
check('_tim live again', robot._tim is not None)
check('OS_TIMER now True', robot.OS_TIMER is True)

print('IDE Run with no settings block in the workspace (always writes 1)')
with open('robot_settings.txt', 'w') as f:
    f.write('OS_TIMER=0\n')                        # stale file from an old project
robot.apply_settings()
check('stale file had stopped the timer', robot._tim is None)
fakehw.TIMER_EVENTS.clear()
exec(IDE_PRELUDE('1'), {})                         # block absent -> BIPES writes 1
check('stale OS_TIMER=0 cannot survive a plain run', robot._tim is not None)
check('file rewritten to 1', open('robot_settings.txt').read().strip() == 'OS_TIMER=1')

print('Standalone boot: settings file on flash, then main.py head')
for value, expect_timer in (('1', True), ('0', False)):
    with open('robot_settings.txt', 'w') as f:
        f.write('OS_TIMER=%s\n' % value)
    sys.modules.pop('robot', None)
    fakehw.TIMER_EVENTS.clear()
    ns = {}
    exec(MAIN_PY_HEAD.replace('robot.cal_gate()', 'pass'), ns)   # cal_gate blocks on a tap
    r = ns['robot']
    check('main.py head with OS_TIMER=%s -> timer %s'
          % (value, 'ON' if expect_timer else 'OFF'),
          (r._tim is not None) is expect_timer, repr(fakehw.TIMER_EVENTS))
    check('  OS_TIMER attribute matches', r.OS_TIMER is expect_timer)

print('Standalone boot with NO settings file behaves like the pre-feature OS')
os.remove('robot_settings.txt')
sys.modules.pop('robot', None)
fakehw.TIMER_EVENTS.clear()
ns = {}
exec(MAIN_PY_HEAD.replace('robot.cal_gate()', 'pass'), ns)
check('timer started', ns['robot']._tim is not None and ('init', 0) in fakehw.TIMER_EVENTS)
check('OS_TIMER True', ns['robot'].OS_TIMER is True)

os.chdir(HERE)
shutil.rmtree(scratch, ignore_errors=True)
print()
print('ALL PASS' if not fails else 'FAILURES: ' + repr(fails))
sys.exit(1 if fails else 0)
