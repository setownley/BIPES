# DEPLOYMENT.md — BIPES fork: local dev → Railway, one identical artifact

The migration guarantee: the container you run locally with `./dev.sh docker`
is byte-identical to what Railway builds and runs. Nothing changes at
migration time except who runs it.

## Verification status of this document (read first)

| Claim | How verified | Confidence |
|---|---|---|
| Plain BIPES clone serves the full IDE with no build step, no submodules | Cloned github.com/BIPES/BIPES (master), served it, curl-checked /ui/, Blockly bundles, block_definitions.js, generator_stubs.js, esp32.xml — all 200 | HIGH |
| Entry point is `/ui/`; root `/` is a 2-second meta-refresh redirect to it | Read root index.html in the clone | HIGH |
| Missing git submodules (blockly, freeboard, databoard) don't break the IDE | Compiled Blockly bundles are committed in ui/core/; freeboard only linked as optional dashboard page | HIGH |
| nginx template renders and serves the real BIPES tree with no-cache + gzip | envsubst-rendered, `nginx -t` passed, ran nginx 1.24 against the clone: all 200, Cache-Control: no-cache, 252 KB js gzipped to 39 KB | HIGH |
| Railway auto-builds a root Dockerfile and injects PORT at runtime | Railway docs (docs.railway.com/builds/dockerfiles, /public-networking), July 2026 | HIGH |
| Dual-stack listen (v4 + [::]) is the right Railway bind | Railway docs say 0.0.0.0:$PORT; a Mar-2026 report shows Railway's proxy connecting via IPv6 and 502ing v4-only binds; dual-stack covers both and matches the nginx image's own default | MEDIUM — see "If Railway 502s" below |
| The exact Docker image was built and run | NOT TESTED — no Docker daemon in my validation environment. Config validated by nginx -t + live serve outside Docker. First `./dev.sh docker` run on your PC is the remaining test | — |
| localhost is a secure context for Web Serial (no HTTPS needed locally) | Chromium platform behavior, long-documented | HIGH |
| Railway pricing/plan sufficient for class hours | NOT VERIFIED — I lack current pricing data; check your plan's usage before relying on it for a lesson | LOW |

## 1. Repo setup (once)

```bash
# Fork BIPES/BIPES on GitHub first (keeps upstream pullable), then:
git clone https://github.com/<you>/BIPES.git bipes-classroom
cd bipes-classroom
git remote add upstream https://github.com/BIPES/BIPES.git

# Drop in the added files from this package, preserving paths:
#   Dockerfile                      (repo root)
#   .dockerignore                   (repo root)
#   deploy/default.conf.template
#   dev.sh
#   firmware/robot.py  firmware/boot.py  firmware/provision.sh
#   firmware/ssd1306.py             (download per handover link)
git add -A && git commit -m "classroom deploy scaffolding + firmware v0.1.0"
```

Where your ongoing edits go (paths verified against the real repo):

| What | File |
|---|---|
| Block appearance | `ui/core/block_definitions.js` |
| Generated Python | `ui/core/generator_stubs.js` |
| Kid palette | `ui/toolbox/esp32.xml` (or add `ui/toolbox/classroom.xml`) |
| Robot runtime | `firmware/robot.py` (bump VERSION on every change) |

One repo = one version. A git tag (e.g. `class-2026-07-20`) pins the exact
block set AND the exact robot.py that were tested together.

## 2. Daily development loop (your PC)

```bash
./dev.sh              # python http.server on :8000
# open http://localhost:8000/ui/  in Chrome/Edge
# edit ui/core/*.js -> refresh browser -> drag blocks -> USB connect -> run on robot
```

Web Serial works here because localhost is a secure context. It will NOT
work for another machine hitting your PC over LAN http — that's the case
Railway exists for.

Before pushing anything you'll rely on in class, run the parity check once:

```bash
./dev.sh docker       # builds + runs the exact Railway artifact on :8000
```

If this crash-loops with "Address family not supported by protocol", your
Docker host has IPv6 disabled — that is a local-environment quirk (my
validation sandbox had it). Fix the host (enable IPv6) rather than editing
the template; the [::] line exists for Railway.

## 3. Migration to Railway (30 minutes, do it a week early — not the night before)

1. Push the repo to GitHub (private is fine — Railway reads via its GitHub app).
2. Railway dashboard → New Project → Deploy from GitHub repo → select the fork.
   Railway detects the root Dockerfile automatically. Do NOT add a
   railway.json/railway.toml — a stray startCommand overriding the image
   entrypoint is a documented failure mode.
3. Service → Settings → Networking → Generate Domain. If it asks for a target
   port, leave it to the PORT variable / default; nginx listens on whatever
   Railway injects.
4. Open `https://<your-domain>.up.railway.app/ui/` — HTTPS is automatic,
   which is what makes Web Serial work for the students' machines.
5. From then on: `git push` to the selected branch = automatic redeploy.
   Rollback = Railway dashboard → Deployments → redeploy a previous one.

**If Railway shows "Application failed to respond" (502):** check deploy logs
first. If nginx started but the proxy can't reach it, the v4/v6 bind is the
suspect — the template listens on both, which per current docs and field
reports should work; if it doesn't, that's new Railway behavior and the fix
is adjusting the listen lines per their troubleshooting page, not the app.

## 4. Robot provisioning (once per board + after any robot.py change)

```bash
pip install esptool mpremote
cd firmware
./provision.sh /dev/ttyACM0        # repeat per board / per port
```

The script erases, flashes MicroPython, copies boot.py + robot.py +
ssd1306.py, then runs a smoke test that imports robot (which starts Timer 0
and paints the OLED), blinks the blue LED for 1 s, and shuts down cleanly.
A board that passes has proven: USB, flash, filesystem, I2C/OLED, Timer 0,
and the LED — before a child ever touches it.
NOT YET RUN ON REAL HARDWARE — script is syntax-checked only; validate on
one board before batch-running it on twenty.

## 5. Pre-class checklist (morning of)

1. `https://<domain>/ui/` loads in Chrome on a student machine (not just yours).
2. USB connect on that machine → REPL prompt appears.
3. `import robot; robot.VERSION` over the REPL matches the version your
   blocks were tested against.
4. One end-to-end run: drive-forward block + stop button → motors halt.
5. Known dependency: if Railway is down during class you have no fallback —
   LAN-serving from your laptop won't give students Web Serial (insecure
   remote origin), and bipes.net.br lacks your custom blocks. If that risk
   is unacceptable, deploy the same repo to a second static host as a spare
   URL (any HTTPS static host works; the artifact is just files).
