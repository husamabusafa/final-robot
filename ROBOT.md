# The Robot

A Reachy Mini desk robot that holds a real spoken conversation, watches the room
through its camera, moves its body as it talks, and drives a separate
presentation screen while it speaks.

Everything runs from one process on the robot's Raspberry Pi (`main_pi.py`). It
needs no laptop in the loop: the Pi does vision locally, talks to Gemini Live
over the internet for voice, and pushes screen events out to a deployed web
panel.

## What it is made of

| Layer | What it does |
|---|---|
| Reachy Mini SDK / daemon | Motors, head IK, camera, speaker/mic, recorded-move playback, daemon-side head tracking and audio-reactive wobble |
| Local vision (OpenCV) | YuNet face detection + SFace face recognition + mouth-motion "who is talking", ~30 FPS on the Pi |
| Gemini Live | Full-duplex speech-to-speech with function calling; the robot's brain and voice |
| Presentation panel | A deployed web screen the robot publishes to over WebSocket |
| Local web server (`:8080`) | Live annotated camera stream + a dependency-free fallback screen |

There is no wake word and no push-to-talk. The mic is always streaming, and
Gemini's server-side VAD decides when someone is speaking.

## Senses

**Sight.** Frames come from the daemon camera at ~30 FPS. Every frame is run
through YuNet face detection (320 px inference, 5 landmarks per face). Every 15th
frame the detected faces are embedded with SFace (128-d) and matched against a
local JSON face database by cosine similarity, so identity is continuous but
cheap. The same aligned crop is reused for a mouth-region variance measure, which
gives an energy score per face — the highest one is treated as "the person
currently speaking", entirely visually.

Separately, a JPEG of the latest frame is streamed to Gemini so the model can
actually *see*. The stream is gated rather than constant: full rate while a
person is speaking (plus a 5 s tail) and while the robot itself is speaking, and
otherwise one ambient heartbeat frame every 2 s. This keeps replies fast without
letting the model answer "what is this?" from a stale image.

**Hearing.** The mic is teed into Gemini at 16 kHz mono. Because the robot's own
speaker bleeds into its mic, the mic is gated while the robot talks, and the
gate is adaptive: the system measures the live bleed level and only lets audio
through when it is confidently louder than the bleed, for several consecutive
chunks. That is what makes barge-in work — you can talk over the robot
mid-sentence and it stops and listens.

**Touch.** Pulling an antenna while the robot is talking makes it stop. It is
detected as a deviation between the commanded and present antenna position (a
firm ~14° pull against the servo), with hysteresis so it fires once per pull and
never during a body-language clip.

**Memory of people.** Faces are enrolled by name on request and persisted to
`data/faces/sface_db.json`, so the robot still recognises people after a
restart.

## Voice and conversation

- Gemini Live, speech-to-speech, `gemini-3.1-flash-live-preview` by default
  (overridable with `--model` / `GEMINI_MODEL`), prebuilt voice `Puck`.
- Aggressive VAD tuning (250 ms silence, high start/end sensitivity, 20 ms
  prefix padding) so replies come back quickly, with
  `START_OF_ACTIVITY_INTERRUPTS` so the model yields the floor as soon as a
  person starts talking.
- Minimal thinking level and low media resolution, both chosen for latency.
- Session resumption, so a dropped network link resumes the conversation
  instead of restarting it.
- It is bilingual by design: Arabic by default, switching to English for as long
  as the person speaks English, then back.
- The persona is a small, warm, curious desk companion — short replies, no
  narrating its own actions, no asking permission before using a tool.

Its knowledge comes from a local markdown knowledge base appended to the system
instruction, plus an optional "latest updates" section fetched from the panel at
startup, so facts can be edited from a browser without touching the Pi.

## Body language

All motion is SDK-native; nothing is hand-animated except the antenna breathe.

- **Head tracking** runs daemon-side (`start_head_tracking`, weight 0.6). The
  robot follows the nearest face by default.
- **Speaking motion** is `enable_wobbling()`: the SDK analyses the actual
  speaker output and composes 6-DOF head offsets before IK, so head sway follows
  loudness and layers on top of tracking instead of fighting it.
- **Emotions** are real recorded clips from
  `pollen-robotics/reachy-mini-emotions-library`, played at 100 Hz across head,
  body yaw and antennas with sidecar audio. A curated conversational subset of
  ~25 is exposed to the model (welcoming, cheerful, curious, amazed, grateful,
  laughing, thoughtful, confused, oops, relief, success, yes, no, shy, calming,
  tired, dance, …). While a clip plays it owns the robot: head tracking pauses
  and the antenna breathe is muted.
- **Antennas** idle-breathe at 0.22 Hz so the robot never looks switched off.
- **Manual looks** (`look_left`, `set_head_angle`, …) take over the head, then
  hand it back to tracking.

On startup it enables motors and wakes up; on shutdown it cancels any clip, zeroes
the wobble offsets, and goes to sleep cleanly.

## The presentation screen

The screen is a separate web app (`panel/`, Vite + React + a Fastify relay) so
any device — a TV, a laptop, a phone — can just open a URL. The robot connects
*out* to the relay as a WebSocket publisher, so it works from behind NAT with no
port forwarding.

Updates are incremental events (`dashboard.begin`, `dashboard.tile`,
`video.show`, `page.show`, `display.clear`, `robot.status`). The relay folds
them into a state it replays in full to any device that joins mid-presentation,
so a screen can be plugged in halfway through and catch up. The robot's
in-process state is the source of truth; if the panel is unreachable, events are
dropped rather than queued and the whole state is replayed on reconnect.

Six tile types, max six tiles per screen:

| Type | Use |
|---|---|
| `kpi` | 2–6 headline numbers, counted up on arrival |
| `bar` | compare entities on one metric |
| `pie` | breakdown of a whole |
| `line` | trend over time |
| `table` | non-numeric facts (`text_values`) |
| `map` | pins on a MapLibre dark basemap, by centre+zoom or up to 8 markers |

It can also take over the whole screen with a YouTube video or an arbitrary web
page, chosen by fuzzy-searching a local catalog (`urls.json`) of titles,
companies and keywords.

Two design properties are deliberate and worth knowing:

- Tiles are *appended*, never re-broadcast as a batch, so existing tiles never
  re-mount and replay their count-up animations.
- Model arguments are repaired rather than rejected — `"740,000"` and `"1.2M"`
  are coerced to numbers, mismatched arrays truncated, item counts clamped —
  because a rejected tool call makes the robot apologise out loud mid-demo,
  which is worse than a rounded value.

There is also a local fallback screen at `http://<robot>:8080/display`:
deliberately dependency-free (no CDN fonts, no chart library) so it still works
for a demo with no internet, polling `/api/display`.

## What the model can actually do (tools)

**Movement** — `look_straight`, `look_left`, `look_right`, `look_up`,
`look_down`, `set_head_angle(yaw, pitch)` (±60° yaw, ±30° pitch),
`enable_face_follow`, `disable_face_follow`.

**Body language** — `play_emotion(name)`.

**People** — `enroll_face(name, position?)`, `identify_person`,
`find_person(name)`, `list_known_people`, `who_is_speaking`, `focus_on_person`,
`focus_on_speaker`, `clear_focus`, `describe_scene`.

**Screen** — `add_tile(...)` (one call per tile, 3–4 in a row to build a
dashboard), `clear_display`, `show_content(query)`.

**Utility** — `ping`, `get_robot_status`.

Tools that need the camera answer from the latest frame synchronously, so the
model can search the room autonomously: look in a direction, check what it sees,
move again, and only speak once it has found the thing or exhausted the
directions.

## Interfaces

| Endpoint | What |
|---|---|
| `http://<robot>:8080/` | Live annotated MJPEG stream with an FPS / faces / tracking / voice HUD |
| `http://<robot>:8080/stream` | Raw MJPEG |
| `http://<robot>:8080/display` | Offline fallback presentation screen |
| `http://<robot>:8080/api/display` | Current screen state as JSON |
| Panel `/panel` (WS) | Screens subscribe here |
| Panel `/robot` (WS) | The robot publishes here, token-authenticated |
| Panel `/api/knowledge` | Read/write the live knowledge text |
| Panel `/healthz` | Health check |

## Running it

```bash
.venv/bin/python main_pi.py
```

Useful flags: `--no-gemini` (motion only, no voice), `--voice`, `--model`,
`--video-fps`, `--no-face-recognition`, `--track-weight`, `--no-wobble`,
`--no-emotions`, `--volume` / `--quiet`, `--log-level`.

Environment: `GEMINI_API_KEY` for voice, `PANEL_URL` + `HSAFA_PANEL_TOKEN` for
the deployed screen. With no `PANEL_URL` it runs fully local; with no API key it
still tracks faces and streams video.

Face models (YuNet, SFace) are downloaded into `models/` on first run.

## Failure behaviour

The robot is built so the demo degrades instead of dying:

- Panel unreachable → screen events dropped, robot keeps talking, screen catches
  up on reconnect.
- Internet down → local `:8080/display` still shows dashboards and the camera
  stream still works.
- Remote knowledge fetch fails → silently falls back to the local knowledge file.
- Emotions library unavailable → `play_emotion` is simply not advertised to the
  model, so it can never call a clip that cannot be played.
- No audio device → voice disables itself and vision keeps running.
- A malformed tool argument → repaired, not refused.
