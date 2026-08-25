# Hsafa Console — Robot Control Plane

**Version:** 2.0
**Status:** Architecture agreed, not built.
**App:** `panel-admin` (client) + `console/` (gateway) + `agent/` (on-robot), siblings to `panel`.

Supersedes v1.x, which specified the UI down to the type scale before deciding
what the product was. The design system in that draft was good work and is not
lost — the surface list in §12 is what survives. Everything else here is about
the system.

---

## 1. What this is

The Rafed robot works. One `main_pi.py` on one Pi, one hand-edited `.env`, one
`rafed_knowledge.md`, one deployed screen, and a demo Rafed liked. Getting to
that took SSH, rsync, a soldering-iron level of familiarity with the SDK, and me
in the room.

That does not survive contact with a second customer. Everything that makes the
robot good is currently *configuration held in a repo I own*: the persona, the
knowledge base, the tool set, the video catalog, the motion tuning, the API key.
Handing a robot to a company today means handing them a thing they cannot change
and cannot restart.

**The product is the layer that makes the robot a deliverable.** One hosted
console where a company's own staff can:

- see their robots, and whether each one is actually working right now;
- start, stop and restart the experience without SSH;
- edit what the robot knows, how it behaves, and what it can do;
- build actions and triggers so the robot does things without being spoken to;
- get a URL for the presentation screen and put it on any display;
- onboard a brand new robot — including joining it to their Wi-Fi — from a
  browser, in the room, with no terminal.

Rafed is tenant #1 and the design constraint: the console must be able to
express the entire existing Rafed deployment as data, with nothing left in the
repo. If a field is still hardcoded in `main_pi.py` after this is built, the
console has failed at that field.

### 1.1 The one-sentence test

*A Rafed employee who has never seen a terminal receives a robot in a box,
opens the console on their laptop, and has it welcoming visitors in Arabic with
their own numbers on the screen — without calling me.*

Every decision below is judged against that sentence.

---

## 2. Platform reality check

This is the section to read before designing anything, and the reason v1.x of
this plan was unsafe: it assumed capabilities the robot does not have. Sources
are the vendor docs snapshot in `docs/6-third-party-reachy/` plus a verification
pass against the live docs, PyPI and the `pollen-robotics` repos.

### 2.1 What exists and we can build on

| Capability | Detail |
|---|---|
| Daemon REST + WS API | FastAPI on `:8000`, Swagger at `/docs`. Sibling transport to the Python SDK — same `process_command()` backend |
| App lifecycle over HTTP | `GET /api/apps`, `POST /api/apps/start`, `POST /api/apps/stop`, `GET /api/apps/current` |
| App lock | States `free` / `local_app(name)` / `remote_session(name)`. Released in a `finally` on clean exit, crash, SIGKILL and OOM |
| App model | `ReachyMiniApp` subclass, `run(reachy_mini, stop_event)`, registered via a `reachy_mini_apps` entry point. Daemon runs it as a subprocess and SIGINTs it to stop |
| Robot identity | `GET /api/hardware-id` — stable per unit, derived from the audio device serial |
| State telemetry | `GET /api/state/full` (head pose, antennas, body yaw), `GET /api/state/doa`, `GET /api/motors`, `GET /api/daemon/status` (version, hardware id, motor mode, backend) |
| Daemon/SDK OTA | `GET /api/update/available`, `POST /api/update/start`, job logs over `WS /update/ws/logs`. Updates the daemon venv *and* `apps_venv`, then `systemctl restart` |
| Wi-Fi provisioning | Two paths: AP mode (`reachy-mini-ap` / `reachy-mini`, robot at `10.42.0.1`) and a **BLE GATT interface** with `STATUS`, `PIN_XXXXX`, `CMD_WIFI_SCAN`, `CMD_WIFI_CONNECT`, `CMD_HOTSPOT`, `CMD_RESTART_DAEMON`. PIN is the last 5 digits of the serial, throttled against brute force |
| Discovery | mDNS `_reachy-mini._tcp.local.` |
| Outbound NAT story | The daemon already dials out to a central HF signaling server for WebRTC sessions, with backoff. Proof the pattern is expected, not that we can use their relay |
| Motion, media, emotions | `goto_target` / `set_target`, `create_head_pose` (6-DOF), `enable_wobbling`, `start_head_tracking(weight)` + `get_tracked_face`, `play_move` over the emotions and dances HF datasets, `media.get_frame`, `get_DoA`, `imu` (wireless only), `set_motor_mode`, `wake_up` / `goto_sleep` |

### 2.2 What does not exist, and what we do about it

| Missing | Consequence | Our answer |
|---|---|---|
| **Battery level in software** | Documented hardware limitation. The LiFePO4 pack's BMS does not report SoC to the CM4; the only indication is an LED going green → orange → red | We cannot show a percentage and **will not fake one**. §9 |
| Fleet / multi-robot tooling | Nothing official. No hosted control plane, no org model, no remote fleet API | This entire document |
| LAN API authentication | Daemon binds `0.0.0.0`, CORS `*`, and has had an unauthenticated-upload advisory | The agent is the only thing that talks to `:8000`; we firewall it to loopback. §10 |
| Motor temperatures over REST | Visible in the vendor desktop app's hardware monitor, not in the documented REST surface | Treat as unavailable. Use CPU/SoC temp, which we can read, as the thermal signal |
| Docker in the OS image | Apps run in venvs; there is no container runtime on the robot | Docker is a control-plane technology here, not a robot one. §5.3 |
| OS-level OTA | Image updates are a manual reflash over `rpiboot` | Out of scope. We manage the app and the SDK/daemon, not the OS |
| Web dashboard on the robot | Deprecated in SDK 1.9.0 in favour of a desktop app | Good news: we are not competing with a shipping web UI, and the LAN UI we would have had to coexist with is going away |

### 2.3 Hardware facts that constrain the design

Raspberry Pi **CM4**, 4 GB RAM, 16 GB eMMC — not a Pi 5. 9 DOF (6-DOF Stewart
head, body yaw, two antennas, Dynamixel Protocol 2.0). IMX708 camera, 4-mic
XMOS array capped at 16 kHz, 5 W speaker. SSH is `pollen` / `root` on
`reachy-mini.local`, which is to say: **every robot ships with the same
credentials on the LAN.** That is a customer-site security problem we inherit
and must at least not make worse.

4 GB and 16 GB eMMC is the number that kills container-per-app on the robot, and
the reason the vision pipeline is YuNet/SFace instead of anything with torch in
it.

### 2.4 The three constraints that shape everything

1. **One app owns the robot.** The app lock is a real mutex. The console's
   mental model must be "which experience is running", never "run these two
   things at once". A remote WebRTC session (someone opening a Pollen HF Space)
   will evict or be refused against our app — the console has to *show* that,
   because otherwise it looks like our software crashed.
2. **The SDK version must match the daemon.** Already documented in
   `AGENTS.md`, already a range-pin in both requirements files, already a foot
   gun we have shot ourselves with. The agent must never `pip install` a pinned
   `reachy-mini`; it updates the SDK only by asking the daemon to update itself.
3. **The robot is behind someone else's NAT, on someone else's Wi-Fi.** No
   inbound anything. Ever. This is already the panel's architecture and it is
   the only part of the current system that needs no rethinking.

---

## 3. Architecture

```
                    ┌──────────────────────── cloud ────────────────────────┐
 browser            │                                                       │
 ┌──────────────┐   │  ┌─────────────┐   ┌──────────┐   ┌───────────────┐   │
 │ panel-admin  │───┼──│  gateway    │───│ Postgres │   │ panel relay   │   │
 │  (console)   │   │  │  Fastify    │   │          │   │ (per-robot    │   │
 └──────────────┘   │  │  REST + WS  │   └──────────┘   │  screen state)│   │
 ┌──────────────┐   │  └──────┬──────┘                  └───────┬───────┘   │
 │ panel        │───┼─────────┼──────────────────────────────────┘          │
 │ (the screen) │   │         │ device channel (WSS, robot dials out)       │
 └──────────────┘   └─────────┼───────────────────────────────────────────  ┘
                              │
 ┌────────────────────────────┼──────────────── robot (customer LAN) ───────┐
 │  ┌──────────────┐   ┌──────┴───────┐   ┌────────────────────────────┐    │
 │  │ hsafa-agent  │──▶│ daemon :8000 │◀──│ hsafa-app (main_pi.py)     │    │
 │  │ systemd      │   │  (loopback)  │   │  reachy_mini_apps entry pt │    │
 │  └──────────────┘   └──────────────┘   └────────────────────────────┘    │
 │         supervises ▲                              │ Gemini Live (out)    │
 │         config, telemetry, logs                   └─ panel relay (out)   │
 └──────────────────────────────────────────────────────────────────────────┘
```

Four pieces, each with one job.

| Piece | Job | Stack |
|---|---|---|
| `panel-admin` | The console UI. Talks only to the gateway | Vite + React 19 + TS + Tailwind v4 (mirrors `panel`) |
| `console/` gateway | REST for the UI, WS for live data, WS for devices, Postgres for state | Fastify + TypeScript + Postgres |
| `agent/` | The robot's half of the control plane. Always running, never controls motors | Python, systemd, stdlib + `websockets` |
| `panel/` | Unchanged in purpose, but becomes **per-robot** (§8.6) | Fastify + React, already built |

### 3.1 Decisions

**Node + Fastify + Postgres for the gateway.** The panel relay is already
Fastify, `panel/shared/protocol.ts` already proves the shared-types pattern
works across a WS boundary, and the console↔gateway↔device contract is the one
place a type mistake is expensive. One language for three web surfaces. The
counter-argument — Python would let the gateway import the robot's own models —
loses because the gateway must never touch the SDK. Everything SDK-shaped
happens on the robot, behind the agent.

**Postgres, not SQLite, not a document store.** The data is relational and the
queries are joins: robots × orgs × characters × versions × sessions × tool
calls. The tool ledger is the only high-volume table; time-partition it when it
hurts, not before.

**A separate agent process, not a mode of `main_pi.py`.** This is the most
important structural decision here, and it follows directly from §2.4.1: the
robot app can be *stopped*. If the control channel lives inside the app, then a
stopped robot is an unreachable robot, "start" is impossible, and the console
cannot distinguish "off" from "broken". The agent must outlive everything it
manages. It therefore never opens the SDK, never claims the app lock, and never
touches a motor — it drives the daemon's REST API like any other client.

**The agent dials out; nothing dials in.** Same reasoning as the panel, plus:
the daemon's LAN API is unauthenticated, so the agent's second job is to be the
*only* thing that can reach it (§10.2).

**Multi-tenant core, single-org self-host as a deploy flag.** Every table that
holds customer data carries `org_id` from the first migration, and every query
goes through a scope helper. Self-hosting is then "one org, `AUTH_MODE=local`",
not a fork. Retrofitting tenancy onto a single-tenant schema is a rewrite;
adding it now costs a column and a discipline.

---

## 4. The device channel

The contract between the agent and the gateway. Defined in
`console/shared/device-protocol.ts` and generated into Python types for the
agent, the same way `panel/shared/protocol.ts` is the single source of truth for
the screen.

Design rules, inherited from what already works in `panel_client.py`:

- **Outbound WSS, exponential backoff, capped.** One socket per robot.
- **The gateway is authoritative for intent; the robot is authoritative for
  fact.** The console never writes "robot is running" — it writes "should be
  running", and displays what the agent reports.
- **Commands are idempotent and carry an id.** The agent may see a command
  twice after a reconnect; applying it twice must be safe.
- **Telemetry is dropped, not queued.** Same argument as the panel: a stale
  metric is worse than a gap. Events (session started, tool called, error) *are*
  queued, bounded, and drained on reconnect, because those are a ledger.
- **Never trust the agent's clock.** The gateway stamps arrival; the agent's
  timestamp is a field, not the truth.

### 4.1 Message families

| Direction | Message | Payload |
|---|---|---|
| agent → | `hello` | device token, hardware id, agent version, daemon version, SDK version, app version, OS build, ip, hostname |
| agent → | `telemetry` | ~5 s: cpu, mem, soc temp, throttled/undervoltage flags, uptime, disk, app state, app-lock state, daemon reachable, net rtt |
| agent → | `app.state` | `stopped` / `starting` / `running` / `crashed` / `evicted`, pid, exit code, restart count |
| agent → | `event` | session start/end, person recognised, tool call, emotion played, screen change, error — the ledger feed |
| agent → | `log` | ring-buffered app + agent stderr, only while a console operator is subscribed |
| agent → | `config.ack` | applied config version, or the reason it was rejected |
| → agent | `app.start` / `app.stop` / `app.restart` | with a reason string, for the audit log |
| → agent | `config.push` | a full config bundle + version (§6) |
| → agent | `action.run` | an action id + arguments (§8.4) |
| → agent | `update.daemon` | proxied to `POST /api/update/start`, logs streamed back |
| → agent | `agent.update` | self-update to a pinned agent version |
| → agent | `logs.subscribe` / `unsubscribe` | keeps the log firehose off by default |
| → agent | `diag.run` | a named diagnostic bundle (§9.3) |

Version negotiation on `hello`. An agent older than the gateway's floor is told
to self-update before anything else; an agent newer than the gateway is
tolerated. Rolling a fleet forward is not an operation we get to schedule.

### 4.2 What we deliberately do *not* put on this channel

- **Media.** No camera frames, no audio. Live video for the console goes over
  WebRTC from the robot's own stack, or over the existing MJPEG endpoint via a
  console-initiated relay session — never as base64 over the control socket. A
  fleet of robots pushing JPEGs into Postgres-adjacent infrastructure is how
  this design dies.
- **Motor commands at rate.** The console's manual control pad (nudge the head,
  play an emotion) sends *discrete* commands. There is no teleop loop over this
  channel; the round trip through a cloud relay is the wrong shape for a 100 Hz
  control loop, and the SDK's own answer for that is WebRTC.
- **Gemini audio.** The app keeps its own direct connection to Gemini Live. The
  control plane is not in the voice path — it must never be able to add latency
  to a conversation, and a gateway outage must never mute a robot mid-demo.

---

## 5. On-robot runtime

### 5.1 Package `main_pi.py` as a real Reachy Mini app

Today it is a script run by hand over rsync + SSH. It becomes a proper app:

```toml
[project.entry-points."reachy_mini_apps"]
hsafa = "hsafa_app.main:HsafaApp"
```

`HsafaApp.run(reachy_mini, stop_event)` wraps the existing `main()`: it receives
an already-connected `ReachyMini` instead of constructing one, and polls
`stop_event` where the loop currently watches for `KeyboardInterrupt`. Cheap
change; large payoff:

- The **daemon** owns start/stop, the app lock, the SIGINT teardown and the
  return-to-rest afterwards. All the lifecycle correctness we would otherwise
  hand-roll, including the crash path, comes free and is the same code path the
  vendor tests.
- `POST /api/apps/start` becomes the console's Start button. No SSH, no
  `nohup`, no pidfile of our own.
- Config lands as files the app reads at startup, which is already how it reads
  `rafed_knowledge.md` and `.env`.

Ancillary CLI flags (`--voice`, `--track-weight`, `--no-wobble`, …) become
fields in the config bundle. The flags stay for local development; the config
file wins when present.

### 5.2 The agent

A small, boring, dependency-light Python service — `websockets` and the stdlib —
installed as `hsafa-agent.service` with `Restart=always`. Responsibilities:

1. Hold the device channel open.
2. Poll the daemon (`/api/daemon/status`, `/api/apps/current`, robot-app-lock
   status) and the OS (`/proc`, `vcgencmd`) for telemetry.
3. Apply config bundles: write to `/etc/hsafa/config.json` atomically, verify,
   ack the version.
4. Execute commands by calling the daemon's REST API — start/stop/restart app,
   update, sleep/wake, motor mode.
5. Tail the app's stdout/stderr into a ring buffer; ship it only when someone is
   watching.
6. Enforce the desired state: if the console says the app should be running and
   the daemon says it is not, restart it — with exponential backoff and a
   crash-loop cutoff, so a genuinely broken config does not thrash the motors
   every ten seconds.
7. Self-update from a pinned URL, verify the artifact, restart itself.

Explicit non-responsibilities: it does not import `reachy_mini`, does not hold
the app lock, does not talk to Gemini, and has no opinion about faces.

Installed by a one-line bootstrap the customer never runs — the robot is
imaged/prepared before shipping (§8.1). The bootstrap exists for the field.

### 5.3 Why not Docker on the robot

Asked for explicitly, so it deserves a real answer rather than a dismissal.

What containers would buy: reproducible builds, atomic rollback, and immunity
from the SDK/daemon version drift documented in `AGENTS.md`.

Why it loses anyway:

1. **The daemon is on the host and owns the hardware.** A container cannot be
   isolated from it in any meaningful way — it needs `--network host` to reach
   `:8000`, and the audio device is exclusively held by the daemon regardless.
   The container isolates our Python and nothing else, which is what a venv
   already does.
2. **It cannot solve the version-matching problem it exists to solve.** The SDK
   inside the image must match the daemon *outside* it. So the image is pinned
   to a daemon version, and every daemon update requires a coordinated image
   rebuild. That is strictly worse than the current range-pin.
3. **4 GB RAM, 16 GB eMMC, venue Wi-Fi.** Pulling image layers over the network
   the robot happens to be on, minutes before a demo, in a building where the
   Wi-Fi is the least reliable component. eMMC write endurance is not free
   either.
4. **No container runtime in the official image.** Installing one is a
   divergence from a vendor image we do not control and cannot OTA.

**Decision:** the app ships as a wheel into `apps_venv`, managed by the daemon's
app manager; the agent is a wheel plus a systemd unit. Containers are how the
*control plane* ships (§11) — where they are unambiguously correct.

The thing containers were actually wanted for — "one click and the robot is
running the right thing" — is delivered by config versioning plus staged
rollout (§7), which is the property we want. That property does not require a
container; it requires a version number and an ack.

---

## 6. Configuration model

The core abstraction, and the thing that turns the Rafed demo into a product.

**A robot's behaviour is a versioned document, not a filesystem.** Today it is
scattered across `main_pi.py` string literals, `.env`, `rafed_knowledge.md`,
`urls.json` and CLI flags. All of it becomes one composed bundle, resolved
server-side and pushed to the agent.

```
Character  (persona, language policy, voice, motion, VAD, proactivity)
   + Abilities        (which tools exist, their descriptions and schemas)
   + KnowledgePacks   (ordered; base + live updates)
   + ContentCatalog   (what urls.json is today)
   + Actions          (§8.4)
   + Secrets refs     (Gemini key, panel token — refs, never values, in the doc)
   ─────────────────────────────────────────
   = ConfigBundle vN  (immutable, hashed, org-scoped)
```

### 6.1 Rules

- **Bundles are immutable and content-addressed.** Editing a character produces
  a new version; nothing is mutated in place. Rollback is "push v11 again", not
  an undo.
- **Assignment is separate from content.** A robot points at a bundle version.
  Two robots can run different versions of the same character — which is
  precisely how you stage a rollout.
- **Draft vs published.** Editing never touches a running robot. Robots follow
  published versions; a draft is invisible to the fleet.
- **Drift is first-class.** The agent acks the version it actually applied. The
  console shows assigned-vs-running per robot. Silent divergence between what
  the operator thinks a robot is doing and what it is doing is the single worst
  failure mode a fleet console can have.
- **The apply semantics are stated in the UI, per field.** Some changes are
  free, some cost a Gemini session, some cost a process restart. Hiding that
  produces support tickets — we already learned this with `/api/knowledge`,
  which the current `AGENTS.md` documents as "changes apply on robot restart".

### 6.2 Apply cost, and the cheap win

| Change | Cost | Mechanism |
|---|---|---|
| Content catalog, action definitions, thresholds | free | agent writes the file, app re-reads on next use |
| Persona, knowledge, tool set, voice, VAD | **new Gemini session** | `session.reload`: rebuild the system instruction and reconnect Live, keeping the process, the vision loop and the face DB alive |
| Vision params, track weight, media backend | process restart | `app.restart` via the daemon |
| SDK / daemon version | daemon restart | `update.daemon`, robot unavailable ~minutes |

`session.reload` is worth building early. `hsafa_robot/gemini_live.py` already
reconnects on network failure and already resumes sessions
(`SessionResumptionConfig`), so the machinery exists — the change is to allow a
*deliberate* reconnect with a freshly built system instruction. It turns
"restart the robot to change a fact" into a two-second gap in conversation, and
it is the difference between a console people use during a demo and one they are
afraid of.

### 6.3 Secrets

Gemini keys are per-org and BYO-capable. Stored encrypted, referenced by name in
the bundle, and delivered to the agent over the device channel on a separate,
short-TTL request — never embedded in a config document that gets versioned,
diffed and rendered in a browser. Rotation is a first-class operation; the audit
log records that a secret was read, by which robot, when.

---

## 7. Rollout and updates

Three independent version axes, and conflating them is how fleets break:

| Axis | Managed by | Console operation |
|---|---|---|
| Config bundle | us | assign version → agent acks |
| App (`hsafa-app` wheel) | us | staged rollout, canary → fleet, rollback |
| Daemon + SDK | the vendor's updater | trigger `update.daemon`, watch logs |

App rollout: pick a canary robot, push, watch its error rate and session health
for a defined window, then promote. Rollback is pushing the previous wheel
version, which is why the wheel is versioned and kept, not built on the robot.

Daemon updates are *never* automatic and never batched across a fleet. They
restart the daemon, they can change the SDK under our app, and a customer might
be mid-demo. The console surfaces "update available" and requires a human, per
robot, with an explicit "this robot will be offline for a few minutes"
confirmation.

---

## 8. Feature areas

### 8.1 Onboarding — the demo that sells the product

The hard requirement: *a new robot joins the customer's Wi-Fi and appears in the
console without anyone opening a terminal.* This is genuinely achievable, and
the mechanism is BLE.

The robot's BLE GATT provisioning interface (`STATUS`, `PIN_XXXXX`,
`CMD_WIFI_SCAN`, `CMD_WIFI_CONNECT`, `CMD_HOTSPOT`) is reachable from a browser
via **Web Bluetooth**. So the flow is:

1. Operator opens `/onboard` in the console and clicks *Add robot*. The gateway
   mints a short-lived **claim code**.
2. The page requests a BLE device, connects to the robot, unlocks with the PIN
   (last 5 digits of the serial, printed on the unit).
3. `CMD_WIFI_SCAN` → the page lists networks. Operator picks one and types the
   password. `CMD_WIFI_CONNECT`.
4. The robot joins the network. The pre-installed agent starts dialling the
   gateway, presents the claim code and its `hardware_id`, and is bound to the
   org.
5. The console assigns a character and pushes a config bundle. The robot starts
   talking.

Nothing typed into a terminal, no captive portal, no app install.

**Constraints, stated honestly:** Web Bluetooth is Chromium-only — Chrome or
Edge on desktop, Chrome on Android. No Safari, no iOS at all. Onboarding
therefore has a documented fallback path: join the robot's `reachy-mini-ap`
hotspot and use the robot's own settings page, then return to the console and
enter the claim code manually. The console must present the fallback as a normal
option, not an error state, and must detect an unsupported browser *before* the
operator starts.

The claim code + `hardware_id` pairing is what stops a robot from being bound to
the wrong org, and it is why we prefer a code over "whatever agent connects
first".

### 8.2 Fleet and lifecycle

Start, stop, restart the experience. Sleep/wake. Motor mode (enabled / disabled
/ gravity compensation — the last one matters for anyone physically handling the
robot). Per-robot volume and mic mute.

Two things the console must express that a naive version gets wrong:

- **App-lock contention.** If someone opens a Pollen HF Space against this
  robot, our app gets evicted or their session gets refused. That is not a
  crash, and the console must say so in those words: "stopped — a remote session
  took control at 14:32". Otherwise every one of these becomes a support call.
- **Desired vs actual.** A robot whose app the console wants running, that is
  not running, and that has restarted four times in five minutes, is in a
  crash loop. Say *that*, with the exit code and the last 50 log lines,
  instead of showing a red dot.

"Restart" is ambiguous and the ambiguity is operationally dangerous, so the
console offers three explicitly labelled operations: **restart experience**
(app), **restart robot software** (daemon), **reboot** (the Pi). They have
different blast radii and different confirmation copy.

### 8.3 Abilities — the tool system

The robot's capability set becomes editable data. This is the feature that lets
a company make the robot theirs without me writing Python, and it is the deepest
part of the product.

Three tiers:

| Tier | What it is | Editable |
|---|---|---|
| 1 · Built-in | The ~24 tools in `main_pi.py` today — movement, faces, screen, emotions | On/off per character; **description text editable** |
| 2 · Recipe | An ordered sequence of tier-1 calls with templated arguments, exposed to Gemini as one tool | Fully authored in the console |
| 3 · HTTP | Method, URL, headers, body and response template. The robot calls a customer API and speaks the result | Fully authored in the console |

Two non-obvious points that matter more than the tiering:

**A tool's description is prompt engineering, not documentation.** It is the
text the model reads to decide whether to call the thing. Making it editable is
one of the highest-leverage knobs in the product, and the UI must say out loud
that this text is sent to the model.

**Argument repair, not rejection.** `normalize_tile()` in `main_pi.py` exists
because a rejected tool call makes the robot apologise out loud in front of a
customer. That property is now a platform rule: every tier-3 ability gets a
schema, and every schema gets a coercion pass before the call is refused. The
console shows repair rate per tool, because a high repair rate is the signal to
tighten a schema — and a rising one is a regression.

Tier 3 needs real guardrails, because it lets a customer's console user cause
their robot to make arbitrary HTTP requests: allow-list or deny-list by host,
per-call timeout, response size cap, no access to link-local or private ranges
by default, and secrets referenced rather than pasted. This is the one feature
here with a genuine abuse surface and it should ship with the limits on from day
one.

Tool count is itself a tuning parameter: model tool-selection accuracy degrades
somewhere past ~20 tools, so the console counts enabled tools per character and
warns. That is a real finding from the current build, not a guess.

### 8.4 Actions and triggers — the robot acts without being spoken to

Today the robot is purely reactive: someone talks, it answers. The feature asked
for — a button that says "say hi to the guests" — generalises into the most
distinctive thing this console can offer.

An **Action** is a named, parameterised thing the robot does, composed of:

- a spoken intent injected into the live session (Gemini says it in its own
  words, in the right language, rather than reading a canned string);
- optional tool calls (play an emotion, build a dashboard, show a video);
- optional screen state.

The mechanism already exists and is currently unused:
`GeminiLiveSession.inject_client_content()` in `hsafa_robot/gemini_live.py`
sends text into the live session via `send_realtime_input`, deliberately not
`send_client_content` (the SDK warns against interleaving the two). Wiring
`action.run` to it is a small robot-side change. `request_interruption()` is
right next to it, for actions that must cut in.

Injecting an *intent* — "greet the two people who just walked in, briefly, in
Arabic" — rather than a script is what keeps the robot from sounding like a
kiosk. Canned strings are available for the cases where exact wording is a
compliance requirement.

A **Trigger** binds an action to a cause:

| Trigger | Source | Notes |
|---|---|---|
| Manual | console button, per robot | The "say hi to guests" case. Also the demo-driver's remote |
| Schedule | gateway cron, robot-local timezone | `croniter` is already a repo dependency and currently unused |
| Person recognised | robot-side event | "welcome back" for a known face; needs a per-person cooldown |
| New face / room occupied | robot-side event | The proactivity hooks the persona already contemplates |
| Idle for N seconds | robot-side | Re-engage, or drop to an attract loop on the screen |
| Webhook | gateway HTTP endpoint | Customer systems trigger the robot. Signed, per-org, rate-limited |
| Panel event | screen finished a video | Chain a spoken follow-up to what the screen just showed |

Scheduled and webhook triggers evaluate in the **gateway** — the robot must not
be the thing that owns a calendar, because an offline robot silently missing its
schedule is invisible, whereas a gateway can record "fired, robot unreachable".
Perception-driven triggers evaluate on the **robot**, because they need frame
latency and must survive a network outage.

The whole feature needs one hard-won safety property: **a budget**. A robot that
proactively talks every time it sees a face is unbearable within ten minutes.
Per-trigger cooldown, per-robot rate ceiling, quiet hours, and a global "no
proactive speech while someone is mid-conversation" interlock. The console
surfaces the budget as a first-class setting, not a hidden constant.

### 8.5 Knowledge

`rafed_knowledge.md` is 60 KB of verified facts; the panel's `/api/knowledge`
flat file is the live-updates layer on top. Both move into the console as
ordered **knowledge packs** per org, with versions, authorship and diffs.

The existing behaviour is preserved exactly: base pack + live pack, later wins
conflicts, remote fetch failure falls back to the local file silently. The robot
keeps its last-known-good pack on disk so a robot with no internet still knows
things — which is already true today and must stay true.

Improvement over today: the panel's `GET/PUT /api/knowledge` becomes a
compatibility shim over the console's store, so nothing on the robot has to
change on day one.

Realistic near-term addition, not v1: pack size vs. system-instruction budget is
a real ceiling (128 KB today, enforced by the relay). The honest fix is
retrieval rather than a bigger prompt, and that is a separate project.

### 8.6 Screens

The panel already does the hard part. Two changes make it a fleet component:

1. **Per-robot rooms.** Today the relay holds exactly one global
   `DisplayState` and `/robot` accepts a single publisher. It becomes keyed by
   robot: `/robot?id=rm-01`, `/panel?robot=rm-01`, one folded state per robot.
   This is a breaking protocol change and should be done once, deliberately, with
   the version field that `panel/shared/protocol.ts` already carries.
2. **Screen links as managed objects.** The console mints a per-robot screen
   URL, optionally with `?screen=1` for kiosk mode, optionally token-gated for
   customers who do not want a public URL. Named screens, last-seen, viewport,
   and a "reload" command.

The append-only tile discipline stays exactly as documented in `AGENTS.md`:
tiles are appended, never re-broadcast as a batch, because re-sending the list
re-mounts tiles and replays every count-up animation. `MAX_TILES` is mirrored in
two places today and will be mirrored in three; the console must import it from
`panel/shared/protocol.ts` rather than redeclaring it.

### 8.7 People and faces

The face database is currently a JSON file per robot
(`data/faces/sface_db.json`). In a fleet it becomes an org-scoped directory that
syncs to the robots that need it — so a person enrolled at reception is known at
the boardroom robot.

This is the feature with the highest legal exposure and it must be designed for
that from the start, not retrofitted. Rafed is a Saudi entity, so PDPL applies:
biometric data, purpose limitation, retention limits, a deletion path that
actually deletes, and an export. Concretely:

- Face embeddings are personal data. They are encrypted at rest, never leave the
  org, and are deletable per person with the deletion propagating to every robot
  that holds a copy.
- Retention is a policy field with a default, not "forever".
- The console has a visible, single-click **purge** per person and per robot,
  and an audit record of who purged what.
- Enrolment is consented by construction — someone says "I'm Husam" — and the
  console must never offer bulk enrolment from uploaded photos. That is a
  different product with a different legal posture, and we are not building it.

Also worth keeping from the current build: the recognition-margin view (top-1 vs
top-2 similarity) is how a human actually debugs identity flapping, and the
per-person "facts" the model writes are the memory that makes the robot feel
like it knows someone.

### 8.8 Observability

Three surfaces, in priority order.

1. **Tool ledger.** Every tool call: robot, session, turn, tool, raw arguments,
   repairs applied, latency, outcome. This is the highest-value debugging
   artifact in the entire system — it is how you find out that the model called
   `add_tile` with `"740,000"`, or that `play_emotion` is failing on a robot
   whose emotions library did not download. Default sort on the thing that is
   broken.
2. **Sessions and transcripts.** Bilingual transcript, per turn, with the tool
   calls and screen changes inline on a timeline. This is how you answer "what
   did the robot actually say to the minister".
3. **Health.** CPU, SoC temperature, throttling, FPS, Gemini round-trip, panel
   RTT, app restarts. Plus a **version matrix** across the fleet (agent / daemon
   / SDK / app / config) with mismatches highlighted, because §2.4.2 says
   version drift is the failure mode that bites hardest.

Retention: transcripts and tool arguments contain customer speech, which is
personal data. Retention windows are per-org settings with a default, and the
default is short. Sampling raw arguments rather than storing all of them is the
right call once volume matters.

### 8.9 Metering, quotas and billing hooks

"Ready production for companies" implies knowing what a company costs. Gemini
Live is metered by audio-second and the robot is streaming video into it; this
is the dominant variable cost and it is currently unmeasured. The gateway
records session minutes, tool calls and video frames per org, exposes them, and
supports a soft cap with a warning and a hard cap that degrades gracefully —
motion and screen keep working, voice stops — rather than dying mid-demo.

---

## 9. Battery, and telling the truth about it

Explicitly asked for, and the honest answer is that **the hardware does not
expose it.** The vendor documents this as a known design limitation: the LiFePO4
pack's BMS does not report state of charge to the CM4, and the only indication
is an LED. There is no SDK call, no daemon endpoint, and nothing in
`/sys/class/power_supply` to read.

Inventing a percentage from uptime would be worse than showing nothing, because
someone would plan a demo around it.

### 9.1 What we show instead

A **power health** panel built from things that are actually measurable on the
Pi by the agent:

| Signal | Source | Means |
|---|---|---|
| Undervoltage now / since boot | `vcgencmd get_throttled` bits | The strongest real proxy for a draining pack or a weak supply |
| Throttled / capped, now and sticky | same | Thermal or power limiting; correlates with dropped FPS |
| SoC temperature | `/sys/class/thermal` | The thermal signal, since motor temps are not exposed over REST |
| Uptime, and time since last unclean shutdown | `/proc/uptime`, journal | An unclean power-off is very likely a flat battery |
| Battery level | — | Rendered as "not available on this hardware", with a link to why |

An undervoltage event is an **alert**, not a metric buried in a chart: it is the
one signal that reliably precedes a robot dying mid-demo.

### 9.2 The operational answer

Documented, in the console, on the robot page: for anything that matters, run
the robot on mains. The console's pre-demo checklist (§9.3) says so. If a
customer needs real battery telemetry, the paths are a smart plug or inline USB
power meter integration — a separate device, honestly labelled as such — or
waiting for the vendor to expose it. If they do, this becomes one field.

### 9.3 Pre-demo check

A single console button per robot that runs a diagnostic bundle and returns a
pass/fail list: daemon reachable, app running, motors enabled, camera producing
frames, mic gate opening, face models present, emotions library present, Gemini
reachable and authenticating, panel connected, screen subscribed, config version
matching, no undervoltage since boot, disk space, temperature.

This is a small feature and it is probably the one an operator uses most. Every
demo failure this project has had would have been caught by it.

---

## 10. Security and tenancy

### 10.1 Control plane

- Org-scoped everything, enforced in a query helper, not by remembering.
- Roles: owner, operator, viewer. Operators cannot rotate secrets or delete
  people; viewers cannot touch a robot.
- Audit log on every state-changing action: actor, org, robot, before, after.
  Non-negotiable for the "who restarted the robot during the presentation"
  question, which will be asked.
- Device tokens are per robot, long-lived, rotatable, and revocable — revocation
  is what you reach for when a robot is lost or a customer relationship ends.
- Sessions are HttpOnly cookies. The current panel's `sessionStorage` token is
  fine for one admin textarea and not fine for this.

### 10.2 Robot

The uncomfortable inheritance: the daemon's LAN API is unauthenticated with
permissive CORS, and every robot ships with identical SSH credentials. On a
customer's corporate network that is a finding waiting to happen. What we can do
without forking the vendor image:

- Bind the daemon to loopback (or firewall `:8000` to loopback) so the agent is
  the only client. The agent then *is* the authenticated boundary, which is a
  large part of its justification.
- Rotate the SSH password and install a key at preparation time; disable
  password auth.
- Keep the console's MJPEG/debug endpoints off by default in production
  configs; they are development affordances.
- Document the residual risk to the customer instead of quietly hoping. A robot
  with a camera and a microphone on a corporate LAN gets a security review, and
  arriving with an honest answer is worth more than arriving with none.

---

## 11. Deployment

Same shape as the panel, because it works and Coolify is already the target.

```
docker-compose.yml
  gateway    console/   Fastify + static panel-admin build   (Traefik FQDN)
  panel      panel/     unchanged, now per-robot rooms       (Traefik FQDN)
  postgres   volume
```

Carried forward from `AGENTS.md`, learned the hard way and still true: **no
`networks:` section** — Coolify creates its own and Traefik only joins that one,
so a custom network makes routing pick the wrong container IP and requests hang
with 504s. And the `healthcheck` matters: Traefik will not route to a container
it thinks is unhealthy.

Additions this needs and the panel did not: Postgres with a real volume,
migrations that run on boot and are idempotent, and a documented backup. A
control plane whose database is not backed up is not production.

Self-host variant: the same compose file with `AUTH_MODE=local` and a single
seeded org.

---

## 12. Console surfaces

Kept deliberately short. The UI is downstream of §§4–9, and the v1 design system
(dark, borderless, `panel`'s tokens, skeletons not spinners, status never by
colour alone, `dir="auto"` on content fields) carries over unchanged and does not
need respecifying here.

```
FLEET      Overview          /
           Robots            /robots            → /robots/:id
           Onboard           /onboard
BEHAVIOR   Characters        /characters        → /characters/:id (+ versions)
           Abilities         /abilities
           Actions           /actions
           Triggers          /triggers
           Knowledge         /knowledge
PEOPLE     Directory         /people
OBSERVE    Tool ledger       /ledger
           Sessions          /sessions          → /sessions/:id
           Health            /health
           Audit             /audit
SYSTEM     Screens           /screens
           Rollouts          /rollouts
           Usage             /usage
           Settings          /settings          (org, users, secrets, retention)
```

Robot detail tabs: Overview · Live · Config (with drift diff) · Abilities ·
Actions · Screen · Logs · Diagnostics · Danger zone.

The one screen worth designing carefully is **robot detail → Overview**: it must
answer "is this robot fine, and if not, which link in the chain is broken" in
one glance. Camera → vision → Gemini → panel → gateway, as a chain with the
failing link marked, plus desired-vs-actual app state, config version, and the
power health panel from §9.

---

## 13. Build order

Phased so each phase is independently reviewable, and ordered so the risky
unknowns land before the volume work. Per the scope decision, the UI leads on
mock data — with one hardening condition attached.

**Phase 0 — Contract.** `console/shared/device-protocol.ts` and the entity
types, plus the generated Python side. Two days, and it makes the mock honest.

> The condition: the mock layer implements *this* contract, one function per real
> endpoint, same names, same shapes. A UI built against a fictional API is a UI
> that gets rewritten. Built against the real contract with a fake
> implementation, wiring is mechanical — which is exactly the property the v1
> plan was reaching for with its `mock/api.ts` seam.

**Phase 1 — Console on mocks.** Shell, auth, routing, the entity model, and the
surfaces in §12 against fixtures. Rafed-flavoured fixtures: five robots, the
real character, the real knowledge, the real tool set. Fake data that looks fake
makes a correct UI look wrong.

**Phase 2 — Gateway + Postgres.** Migrations, org/user/robot/character/bundle
CRUD, auth, audit. Swap the mock for real calls, surface by surface.

**Phase 3 — Agent + device channel.** The vertical slice that proves the
architecture: a real robot appearing in the console, reporting telemetry, and
starting/stopping on command. This is where the design gets tested, so it should
not be phase 6.

**Phase 4 — Config push.** Bundles, versioning, drift, `session.reload`. The
moment the console can change robot behaviour, it is a product.

**Phase 5 — Actions and triggers.** `action.run` → `inject_client_content`,
manual and scheduled first, perception-driven second, budgets from the start.

**Phase 6 — Abilities.** Tier 1 toggles and description editing, then tier 2
recipes, then tier 3 HTTP with its guardrails.

**Phase 7 — Panel per-robot rooms.** Protocol version bump, screens as managed
objects.

**Phase 8 — Onboarding.** BLE/Web Bluetooth flow, claim codes, fallback path.
Last, because it is the highest-risk browser-API work and everything else is
demonstrable without it.

**Phase 9 — Observability, diagnostics, metering, rollouts.**

Gate each phase on the previous being reviewable. Phases 0 and 3 are where this
build succeeds or fails.

---

## 14. Non-goals

Not a teleop console — no 100 Hz control loop over a cloud relay. Not a
replacement for the vendor desktop app. No OS-level fleet management or
reflashing. No custom WebRTC signaling server in v1; if remote camera view needs
one, that is its own project. No app marketplace. No robot-to-robot
coordination — and specifically no multi-robot floor-control protocol, which the
v1 plan made its signature feature before anyone had two robots in one room. No
bulk face enrolment, ever. No RTL mirror of the console; content fields are
bilingual, the chrome is English.

---

## 15. Open questions

1. **Live camera in the console.** MJPEG over a gateway-brokered tunnel, or a
   real WebRTC path? The first is a day of work and looks bad over WAN; the
   second is a project. Which one does the demo actually need?
2. **Who owns the Gemini key?** Our key with usage billed on, or BYO per org?
   Affects metering, quotas, and the shape of the commercial conversation.
3. **Is the person directory org-wide or per-robot?** Org-wide is the better
   product and the heavier privacy story. Rafed's answer probably decides it.
4. **How much of `main_pi.py` becomes shared library?** Packaging it as an app
   is the moment to decide whether `hsafa_robot/` is a published wheel or stays
   vendored.
5. **Retention defaults** for transcripts, tool arguments and face data — needs
   a decision that survives a customer's legal review, ideally before the first
   one asks.
6. **`main.py` (the 107 KB Mac fork).** It is drifting from `main_pi.py` and
   nothing in this plan manages it. Retire it, or bring it under the same config
   model?
