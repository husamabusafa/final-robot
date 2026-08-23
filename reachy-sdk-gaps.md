# Reachy Mini SDK & Hardware — Capability Gap Analysis

Audit of which Reachy Mini SDK / hardware capabilities this project currently uses,
which it does not, and what each unused capability would buy us.

**Scope of audit:** `main.py`, `main_pi.py`, `hsafa_robot/robot_control.py`,
`hsafa_robot/animation.py`, `hsafa_robot/world_state.py`, `hsafa_robot/gaze_policy.py`,
`wake_up.py`, `live_face_track.py`.

**Reference used:** the local docs snapshot in `docs/6-third-party-reachy/`
(fetched ~2026-08-13 against `main`). Verify exact signatures against the SDK
version actually installed before implementing.

---

## Currently used

| Capability | Where |
|---|---|
| `set_target(head, body_yaw, antennas)` | `hsafa_robot/robot_control.py:422-426` |
| `goto_target(...)` | `main.py:2098`, `main.py:2436`, `wake_up.py:43-59` |
| `media.get_frame()` | `main.py:2311`, `main_pi.py:1535`, `live_face_track.py:240` |
| `media.get_audio_sample()` / `push_audio_sample()` | `main.py:2082`, `main.py:2123` |
| `media.start_recording()` / `start_playing()` | `main.py:1953-1954`, `main_pi.py:1693-1694` |
| `wake_up()` / `goto_sleep()` / `enable_motors()` | `wake_up.py`, `live_face_track.py`, `main_pi.py` |
| `start_head_tracking(weight=)` (daemon-side) | `main_pi.py:1198-1212` — **Pi path only** |

Roughly 6 of ~20 exposed capabilities.

---

## Unused, ranked by payoff

### 1. Head translation (x, y, z) — driving a 6-DOF platform as 3-DOF

`head_pose()` in `hsafa_robot/robot_control.py:118-124` builds a **rotation-only**
matrix. The head is a Stewart platform with 6 DOF: `create_head_pose(x=, y=, z=,
roll=, pitch=, yaw=, mm=True)`. Only `wake_up.py` ever touches `z`.

Cheapest expressiveness win available:

- **z** — breathing on idle, perk up on wake word, slump on idle timeout
- **x** (lean forward) — attention/curiosity when someone starts speaking; lean back on surprise
- **roll** — the curious head-tilt. Currently capped at ±1.2° of talking wiggle; hardware allows ±40°

Unused range, too:

| Axis | Our limit | Hardware limit |
|---|---|---|
| Head pitch | `PITCH_LIMIT = 30°` | ±40° |
| Head roll | ~±1.2° (animation only) | ±40° |
| Head yaw | `YAW_LIMIT = 60°` | ±180° |
| Body yaw | `BODY_LIMIT = 90°` | ±160° |

The real constraint is the **65° head−body yaw delta**, not the individual ranges.
As configured the robot cannot turn to look behind itself even though it physically can.

### 2. `media.get_DoA()` — the field exists and is never filled

`hsafa_robot/world_state.py:131` already declares:

```python
doa_azimuth_deg: Optional[float] = None   # sound direction (2+ mics)
```

and `hsafa_robot/gaze_policy.py:85-95` documents an `azimuth_deg` prior for
"virtual sound candidates" that nothing ever produces. Meanwhile Silero VAD runs
over a tee of the mic stream (`main.py:2081-2095`) to yield only a boolean.
The mic array returns `doa, is_speech_detected` in a single call.

**Unlocks:** turning toward a speaker who is not yet in frame. Today the entire
gaze system is camera-gated — someone speaking from behind the robot produces no
reaction.

**Bonus:** cross-checks lip-motion speaker attribution. A face whose lips move
*and* whose bearing matches the DoA is a far stronger match than either signal alone.

**Cost:** ~30 lines wiring `get_DoA()` → `world.doa_azimuth_deg` → an existing
`GazePolicy` prior. Activates code already written.

### 3. IMU (wireless only) — gyro was removed and nothing replaced it

`robot_control.py` docstring: "No gyro feedback. Removed by request." Reasonable
for the control loop — but the IMU's best use is **event detection**, not stabilization:

- Picked up / moved → react, pause tracking
- Table knock / bump → startle
- Tilt → robot knows it is not level

`mini.imu` returns `accelerometer`, `gyroscope`, `quaternion`, `temperature`.
A ~50-line watcher publishing to the existing event bus (`hsafa_robot/events.py`)
fits the current architecture directly.

### 4. Antennas as input — we only ever write them

Docs: "2 motors, **also usable as physical buttons**." Antenna positions are
written every animation frame and never read back. Free physical UI:

- Push antenna → interrupt Gemini mid-sentence (nicer than VAD barge-in)
- Push → mute mic; push again to unmute
- Push-and-hold → start face enrollment (currently a Gemini tool only)

### 5. Emotions library / `play_move()` — hand-rolled what ships built in

```python
from reachy_mini.motion.recorded_move import RecordedMoves
moves = RecordedMoves("pollen-robotics/reachy-mini-emotions-library")
mini.play_move(moves.get("happy"), initial_goto_duration=1.0)
```

`IdleAnimation` / `TalkingAnimation` in `hsafa_robot/animation.py` are hand-tuned
sinusoids that explicitly zero out head motion to avoid fighting the controller.
Professionally authored emotion clips will read better than sinusoids.

Expose as a Gemini tool (`play_emotion(name)`) alongside the existing 24 tools
(`main_pi.py:860-1106`) and the model becomes expressive on its own.

**Caveat:** `play_move` takes over the joints — gate `RobotController.tick()`
while it plays. Same mechanism as the existing `_manual_override`, but a hard
mute rather than a target swap.

### 6. Motion recording + gravity compensation — author gestures by hand

`mini.start_recording()` / `stop_recording()` plus
`set_motor_mode("gravity_compensation")` lets us physically pose the robot and
capture the trajectory. Beats tuning `ALPHA_YAW = 0.07` and
`math.radians(1.8) * sin(2π·1.3·t)` by feel. Record a nod, a shake, a "thinking"
gesture once and replay them. This is how the `marionette` app works.

### 7. Interpolation methods — we only use the default

Available: `linear`, `minjerk` (default), `ease_in_out`, `cartoon`.

`cartoon` on a glance or double-take is exactly the "alive" quality the sinusoids
are chasing. The manual gaze tools (`look_left`, `look_at`, …) currently route
through the slew filter; a `goto_target(..., method="cartoon")` glance would read
far more intentionally.

### 8. Packaging as a real app — we deploy via scp

Per `wake_up.py:8`:

```
scp wake_up.py pollen@reachy-mini.local:/home/pollen/
```

`reachy-mini-app-assistant create --template conversation <name> <path>` gives
dashboard discoverability, one-click start, proper venv handling, and no manual
scp. `display.html` + `start_display.sh` become the app's `static/` directory.

### 9. WebRTC media backend — may collapse the two codebases

We maintain `main.py` (106 KB, Mac) and `main_pi.py` (66 KB, Pi), and the Pi
version is visibly degraded — no YOLO, no torch, no mediapipe (see
`requirements_pi.txt`). The wireless WebRTC backend streams camera + audio to a
remote machine, so the full pipeline could run on the Mac against the wireless
robot, deleting the Pi fork.

**Two real caveats:**
- Docs say the WebRTC *client* is **Linux-only for now** (macOS pending, tracked upstream)
- Adds network latency to the tracking loop

Worth testing before committing, but ~170 KB of forked logic is significant drift risk.

### 10. Smaller items

- `play_sound(file)` + volume / mic-volume control — earcons for wake, error, enroll-success instead of narrating everything through Gemini
- MuJoCo simulation — there are currently zero tests; sim allows regression-testing the gaze controller without hardware
- REST API at `:8000/docs` — sibling transport to the SDK, useful for the display UI
- Safe torque-off on exit (`gravity_compensation` before disable) rather than just centering

---

## Fix regardless of the above

**Version drift.** `requirements.txt` and `requirements_pi.txt` both pin
`reachy-mini==1.6.3`. PyPI latest is **1.9.0**. Some capabilities listed here
(`playMove`, the animation utilities, auto connection-mode detection) landed
after 1.6.3. Check the changelog before upgrading — this is a robot control
loop, not a leaf dependency.

---

## Recommended order

Best return per hour, each small and independent:

1. **Head translation + roll** — pure expressiveness, no new subsystems
2. **DoA → gaze prior** — activates dead code paths already designed for it
3. **Emotions library as a Gemini tool** — large perceived-quality jump for ~10 lines plus a tick gate
