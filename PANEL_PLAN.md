# Panel + Dashboard Builder — Plan

Move the presentation screen out of the robot into a deployed web app, and rebuild
the dashboard builder so charts appear one-by-one in an advanced-looking layout
with a tool schema Gemini can't get wrong.

## Current state

- `main_pi.py` runs a stdlib `HTTPServer` on the Pi at `:8080`:
  - `/` + `/stream` — MJPEG camera feed
  - `/display` — the presentation page, embedded as the `DISPLAY_HTML` string literal
  - `/api/display` — full display state as JSON
- The browser **polls** `/api/display` every 800 ms and diffs the whole payload.
- `SharedState` (`main_pi.py` ~line 400) holds `display_mode` / `display_charts` /
  `display_video_url`. Tools `show_chart`, `show_content`, `clear_display` mutate it.
- `display.html` at the repo root is a **second copy** of the same page, served by
  `test_display.py` on `:3000` for local preview. Two sources of truth.

### Why it looks janky today

`renderDashboard()` does `dashGrid.innerHTML = ""` and rebuilds every tile on each
poll where the payload changed. So when Gemini adds tile #3, tiles #1 and #2
re-mount and re-run their count-up animations. Fixing this needs push-based,
append-only updates — not a faster poll.

## Decisions

| Question | Decision |
|---|---|
| Realtime transport | Self-hosted WebSocket relay (holds last state, replays to late joiners) |
| App framework | Vite + React + TS + Tailwind — **not** Next.js |
| Server | Fastify, one process: serves the built client **and** the WS endpoints |
| Deploy | Coolify (Docker Compose; Traefik gives TLS + WS upgrade for free) |
| Camera feed in panel | No — dashboard + videos only; camera stays on local `:8080` |
| Widget set | Tight: 5 types |
| Chart library | Recharts (+ framer-motion for entrance/layout animation) |

### Why a relay and not SSE from an API route

- Incremental "charts appear one by one" needs push.
- A device opening the link mid-presentation must see the dashboard **already
  built** — so something must remember the ordered tile list. The relay does this
  natively; an SSE route needs the same store bolted on and loses it on every
  rebuild/restart.
- The Pi is behind NAT. As a WS *client* dialling out to `wss://…/robot` it works
  on any network, auto-reconnects, and gives a free "robot online" heartbeat.

### Why Vite and not Next.js

The panel is one fullscreen kiosk page whose entire content arrives over a
WebSocket. No SEO, no SSR, no server-side data fetching, no auth, no multi-page
routing — every reason to reach for Next.js is absent. Vite instead gives:

1. **One service, not two.** The relay is already a Node process, so it serves the
   built `dist/` too. One Compose service, one Dockerfile, one domain.
2. **No runtime-config problem.** Next bakes `NEXT_PUBLIC_*` at build time, which
   would have forced a `/api/config` endpoint. Same-origin means the client just
   does `new WebSocket(\`wss://${location.host}/panel\`)` — nothing to configure,
   and no CORS.
3. **Faster iteration** on a chart-heavy page, which matters in step 3.
4. **Smaller image, simpler build** — no `standalone` output or `.next` tracing.
5. **Offline-safe fonts** — Tajawal self-hosted via `@fontsource`. Today
   `display.html` pulls it from the Google Fonts CDN, so flaky venue wifi breaks
   the Arabic type mid-demo.

Given up: SSR, file-based routing, `next/image`, API routes — none needed. If
shareable per-company URLs or an admin area ever appear, the components port over
unchanged since they're just Recharts + framer-motion.

## Target layout

One npm package, one deployable image:

```
final-robot/
  panel/
    shared/protocol.ts          message contract, imported by client AND server
    server/index.ts             Fastify: /robot, /panel, static dist/
    src/                        React client (Vite)
    Dockerfile
  docker-compose.yml            single service; runs locally and on Coolify
  scripts/simulate.py           replays a scripted dashboard build (no robot needed)
  hsafa_robot/panel_client.py   asyncio WS client used by main_pi.py
```

The server is TS bundled with esbuild so it shares `shared/protocol.ts` types with
the client — the message contract is the one place a mistake would be expensive.

## Protocol

Two WS endpoints, same origin as the page:

- `/robot` — single publisher, `HSAFA_PANEL_TOKEN` in env, never committed.
- `/panel` — N read-only subscribers.

Events are **incremental**, not full-state snapshots:

| Event | Payload | Panel effect |
|---|---|---|
| `dashboard.begin` | `{ title }` | clear grid, show header |
| `dashboard.tile` | `{ tile }` | append ONE tile, animate it in |
| `video.show` | `{ url, title }` | switch to video mode |
| `display.clear` | `{}` | back to idle screen |
| `robot.status` | `{ online, speaking }` | status dot |
| `sync` | `{ state }` | full state, sent by relay on panel connect |

- Relay keeps `latestState` (ordered tile list) and replays it via `sync`.
- Robot keeps an offline queue and re-sends on reconnect.
- Every message carries `{ v: 1, seq }` so the panel can detect gaps and resync.

## Dashboard builder

### Tool contract

Replace `show_chart` with one tool, `add_tile`, and five types:

| type | use | shape |
|---|---|---|
| `kpi` | big animated numbers (2–6) | `labels[]` + `values[]` |
| `bar` | compare entities on one metric | `labels[]` + `values[]` |
| `pie` | breakdown / share | `labels[]` + `values[]` |
| `line` | trend over time | `labels[]` (years) + `values[]` |
| `table` | facts that aren't numeric | `labels[]` + `text_values[]` |

Every type takes the **same two parallel arrays** — one mental model, so the schema
itself can't be got wrong. Optional `unit` (`"طالب"`, `"%"`, `"ريال"`) drives
formatting. Optional `dashboard_title` on the first call.

### Server-side auto-repair

Fix Gemini's arguments in the tool handler instead of returning errors that derail
the conversation:

- Coerce `"740,000"`, `"740 ألف"`, `"1.2M"` → numbers.
- Mismatched array lengths → truncate to the shorter one, don't fail.
- Clamp item counts per type (`kpi` ≤ 6, `pie` ≤ 6, `bar` ≤ 8) so tiles never look cramped.
- Drop duplicate tiles; cap the grid at 6 (oldest rolls off).
- Return a nudge: `{"ok":true,"tiles_now":2,"note":"Add 1-2 more tiles for a full dashboard."}`
  — steers Gemini to 3–4 tiles without more prompt text.

### Layout that always looks good

- Fluid 4-column grid; column span by type (`kpi`/`line` span 2, `bar`/`pie`/`table`
  span 1). One tile fills the screen, three balance, six tile cleanly.
- Auto-scaling numerals, staggered entrance, dark glass theme, Tajawal + RTL preserved.
- New tiles animate in; existing tiles never re-mount (React keys + append-only state).

### System instruction

Rewrite the SCREEN section of `DEFAULT_SYSTEM_INSTRUCTION` as one short worked
example (company question → four named tiles) instead of the current prose rules.
Concrete examples cut tool-call errors far more than added rules do.

## Robot-side changes (`main_pi.py`)

- `SharedState` becomes an emitter: `add_chart` / `set_video` / `clear_display` also
  push events to the panel client.
- `hsafa_robot/panel_client.py` — `websockets` client, exponential-backoff reconnect,
  offline queue, heartbeat. Fully non-blocking: the panel being down must never
  stall Gemini or the vision loop.
- Keep the `:8080` MJPEG camera stream as-is (local debug).
- **Delete the duplicated `DISPLAY_HTML`** blob; keep one minimal local fallback page
  for no-internet demos. Retire `display.html` / `test_display.py` in favour of the
  panel + `scripts/simulate.py`.
- Add `websockets` to `requirements_pi.txt`.

## Deploy (Coolify)

- One Docker Compose resource, one service (`panel`), one FQDN via
  `SERVICE_FQDN_PANEL_3000` → `https://panel.<domain>`. Traefik terminates TLS and
  upgrades `/robot` and `/panel` with no extra config.
- `HSAFA_PANEL_TOKEN` in Coolify secrets; the robot's `.env` gets `PANEL_URL` plus
  the same token.
- Panel subscribers need no token (read-only).
- The same Compose file runs locally, so dev == prod.
- Optional `?screen=1` kiosk mode (no cursor, no scrollbars) for the presentation laptop.

## Build order

1. `panel/` scaffold + `shared/protocol.ts` + Fastify relay + `scripts/simulate.py` —
   verify push and late-joiner replay with no robot.
2. Panel shell — idle screen, incremental dashboard, video mode, robot status dot.
3. Widget set + layout engine + visual polish.
4. `panel_client.py`, rewire `main_pi.py` tools, new `add_tile` schema, system-instruction rewrite.
5. Dockerfile + Compose + Coolify notes in `AGENTS.md`.

## Open

- Panel subdomain.
- Public URL vs a light `?k=<key>` gate. Public is fine for a demo screen, but a
  shared link becomes indexable.
