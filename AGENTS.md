# final-robot

Hsafa: a Reachy Mini desk robot with Gemini Live voice, face recognition, and a
deployed presentation screen.

## Layout

| Path | What |
|---|---|
| `main_pi.py` | Everything that runs on the Pi: vision loop, Gemini Live, tools, MJPEG server |
| `hsafa_robot/` | Supporting modules (Gemini session, face DB, tracking, panel client) |
| `panel/` | The presentation screen: Vite + React client and Fastify relay, one deployable image |
| `scripts/simulate.py` | Drives the panel with a scripted dashboard, no robot needed |
| `rafed_knowledge.md` | Rafed-focused knowledge appended to the system instruction (verified warehouse numbers as of 2026-08-23 + official figures) |
| `tatweer-rafed-tetco-tbc-talimia.md` | Old group-wide KB (TETCO/Talemia/TBC/Rafed) — kept for reference, **not loaded** |
| `urls.json` | Video catalog searched by the `show_content` tool |

## Live knowledge updates

`rafed_knowledge.md` is the robot's base KB and its offline fallback. On top of
it, the panel hosts an editable "extra knowledge" text so facts can be updated
without touching the Pi:

- Editor at `https://robot-pannel.hsafa.com/admin`, guarded by
  `HSAFA_PANEL_TOKEN`.
- Relay endpoints: `GET/PUT /api/knowledge` (token required). Stored in a flat
  file (`KNOWLEDGE_PATH`, default `<cwd>/data/knowledge.md`; the compose
  `panel-data` volume makes it survive redeploys).
- The robot fetches it in `build_system_instruction()` via
  `fetch_remote_knowledge()` (derives `https://.../api/knowledge` from
  `PANEL_URL`, 5s timeout). On any failure it silently runs on the local file
  only. Remote text is appended as a "latest updates" section that wins
  conflicts; changes apply on robot restart.

## Running the robot

```bash
.venv/bin/python main_pi.py            # add --no-gemini to skip voice
```

Env (`.env`, never committed):

| Var | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini Live |
| `PANEL_URL` | `wss://robot-pannel.hsafa.com/robot`. Unset = local screen only |
| `HSAFA_PANEL_TOKEN` | Must match the panel deployment |

Local camera/debug stream stays on `http://reachy-mini.local:8080/`, with a
dependency-free fallback screen at `/display` for demos with no internet.

### Getting code onto the Pi

The Pi only runs robot code -- never `panel/` (Coolify builds that) and never
the local `node_modules/` or `.venv/`. Sync with excludes:

```bash
rsync -av \
  --exclude node_modules --exclude .venv --exclude .git \
  --exclude panel/dist --exclude __pycache__ --exclude models \
  /Users/Husam/Dev/final-robot/ \
  pollen@reachy-mini.local:/home/pollen/final-robot/
```

On the Pi, install only non-SDK extras -- see the Animation section about why
`pip install -r requirements_pi.txt` is not allowed to manage `reachy-mini`:

```bash
pip install google-genai python-dotenv websockets silero-vad \
            opencv-contrib-python numpy scipy croniter
python main_pi.py
```

## Panel

The screen is a separate web app so any device can open it on a URL. The robot
connects out to it as a WebSocket publisher, so it works behind NAT.

```bash
cd panel && npm run dev      # client :5173, relay :4001
python3 scripts/simulate.py  # feed it a scripted dashboard
```

Verify before committing panel changes:

```bash
cd panel && npm run typecheck && npm run build
```

To test the production image locally (needs `HSAFA_PANEL_TOKEN` in the repo-root
`.env`, which Docker Compose reads automatically):

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
# -> http://localhost:3100
docker compose -f docker-compose.yml -f docker-compose.local.yml down
```

### How the screen updates

Events are incremental (`dashboard.begin`, `dashboard.tile`, `video.show`,
`display.clear`, `robot.status`); the relay keeps the folded state and replays it
to any device that connects mid-presentation. `panel/shared/protocol.ts` holds
the contract and the `applyEvent` reducer, imported by both the relay and the
client so the state machine exists exactly once.

Tiles are appended, never re-rendered as a batch. Do not "simplify" this into a
full-state broadcast: re-sending the tile list re-mounts existing tiles and
replays every count-up animation, which is what the old polling screen did.

### Deploying to Coolify

Deployed at **https://robot-pannel.hsafa.com**.

1. Create New Resource → **Public Repository** (the git-based option, *not* the
   "Docker Compose" tile, which only takes pasted YAML and has no repo to build
   `./panel` from) → `https://github.com/husamabusafa/final-robot`.
2. Change the build pack from Nixpacks to **Docker Compose**. Branch `main`,
   Base Directory `/`, Docker Compose Location `/docker-compose.yml`.
3. Set the domain to `https://robot-pannel.hsafa.com` and add
   `HSAFA_PANEL_TOKEN` (runtime, not build) matching the robot's `.env`.
4. Deploy, then check `https://robot-pannel.hsafa.com/healthz`.

Never add a `networks:` section to `docker-compose.yml`: Coolify creates its own
network and Traefik only joins that one, so a custom network makes routing pick
the wrong container IP intermittently and requests hang with 504s. The
`healthcheck` matters too -- Traefik won't route to a container it thinks is
unhealthy.

`?screen=1` on the panel URL hides the cursor for the presentation laptop.

## Dashboard tiles

Gemini builds dashboards by calling `add_tile` once per tile, 3-4 times in a row.
Six types: `kpi`, `bar`, `pie`, `line`, `table` (uses `text_values[]`), and
`map` (uses `latitude`/`longitude`/`zoom` or `markers[]`; MapLibre + CARTO dark
basemap, RTL plugin self-hosted in `panel/public/`). The first five share the
same `labels[]` + `values[]` shape.

`dashboard_title` never removes tiles: a dashboard only begins when the screen
is idle/showing a video/empty. Replacing content requires `clear_display` --
Gemini passes `dashboard_title` unreliably, and a late one used to wipe the
whole dashboard mid-build.

`normalize_tile()` in `main_pi.py` repairs the model's arguments rather than
rejecting them -- coercing `"740,000"` and `"1.2M"`, truncating mismatched
arrays, clamping item counts per type. Returning an error instead makes the robot
apologise out loud mid-presentation, which is worse than a rounded value. Keep
that property when editing the tool handler.

`MAX_TILES` is mirrored in `main_pi.py` and `panel/shared/protocol.ts`; change
both.

## Animation

All animation is SDK-native. Do not reintroduce hand-rolled head sway.

- **Speaking**: `mini.enable_wobbling()`. The SDK analyses speaker output and
  composes 6-DOF head offsets *daemon-side, before IK*, so it layers on top of
  daemon head tracking instead of fighting it. Amplitude follows loudness.
- **Expressions**: `EmotionPlayer` + the `play_emotion` tool, backed by
  `pollen-robotics/reachy-mini-emotions-library` (81 clips, sidecar audio).
  Playback drives head/antennas/body at 100 Hz, so it *owns* the robot: head
  tracking is paused and the antenna breathe is muted via `is_playing`.
  `EMOTION_CHOICES` is a curated conversational subset, intersected at runtime
  with what the library actually contains.
- **Antennas**: `AntennaBreather`, idle breathe only. The one hand-rolled piece,
  because the SDK has no antenna speech animation.

Requires **reachy-mini >= 1.8.0 on the daemon**, not just in `apps_venv` —
wobbling is a daemon-side feature. An older daemon ignores the command.

The SDK version in `/venvs/apps_venv` must match the daemon, and both are owned
by the robot's own updater. `reachy-mini` is therefore range-pinned, not exact,
in both requirements files. Do not `pip install -r requirements_pi.txt` on the Pi
to manage the SDK — it will downgrade `apps_venv` out of sync with the daemon.
Install only the non-SDK extras there.

## Known issues

- Committed `.venv` blobs remain in git history. Untracked as of the
  `.gitignore` cleanup, but history was not rewritten.
