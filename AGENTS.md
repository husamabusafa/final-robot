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
| `tatweer-rafed-tetco-tbc-talimia.md` | Company knowledge appended to the system instruction |
| `urls.json` | Video catalog searched by the `show_content` tool |

## Running the robot

```bash
.venv/bin/python main_pi.py            # add --no-gemini to skip voice
```

Env (`.env`, never committed):

| Var | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini Live |
| `OPENROUTER_API_KEY` | `look_at` vision model |
| `PANEL_URL` | e.g. `wss://panel.example.com/robot`. Unset = local screen only |
| `HSAFA_PANEL_TOKEN` | Must match the panel deployment |

Local camera/debug stream stays on `http://reachy-mini.local:8080/`, with a
dependency-free fallback screen at `/display` for demos with no internet.

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

1. New resource → Docker Compose → this repo, file `docker-compose.yml`.
2. Set `HSAFA_PANEL_TOKEN` in the resource's environment.
3. Coolify fills `SERVICE_FQDN_PANEL_3000` and terminates TLS; WebSocket
   upgrades on `/panel` and `/robot` need no extra config.
4. Put `PANEL_URL=wss://<that domain>/robot` and the same token in the robot's
   `.env`.

`?screen=1` on the panel URL hides the cursor for the presentation laptop.

## Dashboard tiles

Gemini builds dashboards by calling `add_tile` once per tile, 3-4 times in a row.
Five types, all using the same `labels[]` + `values[]` shape: `kpi`, `bar`,
`pie`, `line`, `table` (which uses `text_values[]`).

`normalize_tile()` in `main_pi.py` repairs the model's arguments rather than
rejecting them -- coercing `"740,000"` and `"1.2M"`, truncating mismatched
arrays, clamping item counts per type. Returning an error instead makes the robot
apologise out loud mid-presentation, which is worse than a rounded value. Keep
that property when editing the tool handler.

`MAX_TILES` is mirrored in `main_pi.py` and `panel/shared/protocol.ts`; change
both.

## Known issues

- `.venv/` is committed to git. It should be removed from tracking and ignored.
