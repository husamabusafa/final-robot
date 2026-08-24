/**
 * Panel relay + static host.
 *
 * One process serves three things:
 *   GET  /            the built React panel (production only; Vite serves it in dev)
 *   WS   /panel       read-only subscribers (laptop, phones, TV browser)
 *   WS   /robot       the single publisher, authenticated with HSAFA_PANEL_TOKEN
 *
 * The relay owns the authoritative DisplayState so a device that connects
 * mid-presentation immediately receives the dashboard as already built.
 */
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs/promises";
import Fastify from "fastify";
import fastifyWebsocket from "@fastify/websocket";
import fastifyStatic from "@fastify/static";
import type { WebSocket } from "ws";
import {
  PROTOCOL_VERSION,
  applyEvent,
  initialState,
  parseEvent,
  type DisplayEvent,
  type DisplayState,
  type ServerMessage,
} from "../shared/protocol.ts";

const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "0.0.0.0";
const TOKEN = process.env.HSAFA_PANEL_TOKEN ?? "";
const SERVE_STATIC = process.env.SERVE_STATIC !== "false";
const HEARTBEAT_MS = 30_000;

const DIST = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");

// Extra robot knowledge edited via /admin and fetched by the robot at startup,
// so facts can be updated without redeploying the Pi. Persisted on disk;
// KNOWLEDGE_PATH points at a Docker volume in production.
const KNOWLEDGE_PATH =
  process.env.KNOWLEDGE_PATH ?? path.join(process.cwd(), "data", "knowledge.md");
const KNOWLEDGE_MAX_CHARS = 128_000;

if (!TOKEN) {
  console.warn(
    "[relay] HSAFA_PANEL_TOKEN is not set -- /robot is unauthenticated. " +
      "Set it before exposing this to the internet.",
  );
}

// --- state ------------------------------------------------------------------

let state: DisplayState = initialState;
let seq = 0;
const panels = new Set<WebSocket>();
const robots = new Set<WebSocket>();

function send(socket: WebSocket, msg: ServerMessage) {
  if (socket.readyState === socket.OPEN) socket.send(JSON.stringify(msg));
}

/** Apply an event and fan it out to every panel. */
function publish(ev: DisplayEvent) {
  state = applyEvent(state, ev);
  seq += 1;
  const msg = { v: PROTOCOL_VERSION, seq, ...ev } as ServerMessage;
  const payload = JSON.stringify(msg);
  for (const p of panels) if (p.readyState === p.OPEN) p.send(payload);
}

// --- server -----------------------------------------------------------------

const app = Fastify({ logger: { level: process.env.LOG_LEVEL ?? "info" } });
await app.register(fastifyWebsocket, { options: { maxPayload: 256 * 1024 } });

app.get("/healthz", async () => ({
  ok: true,
  panels: panels.size,
  robot: state.robot.online,
  seq,
}));

// --- robot knowledge (edited on /admin, fetched by the robot) ---------------

type AuthedRequest = {
  query?: unknown;
  headers: { authorization?: string };
};

function suppliedToken(req: AuthedRequest): string {
  return (
    (req.query as Record<string, string | undefined>)?.token ??
    req.headers.authorization?.replace(/^Bearer\s+/i, "") ??
    ""
  );
}

app.get("/api/knowledge", async (req, reply) => {
  if (TOKEN && suppliedToken(req) !== TOKEN) {
    return reply.code(401).send({ error: "unauthorized" });
  }
  try {
    const text = await fs.readFile(KNOWLEDGE_PATH, "utf8");
    const stat = await fs.stat(KNOWLEDGE_PATH);
    return { ok: true, text, updated_at: stat.mtime.toISOString() };
  } catch {
    return { ok: true, text: "", updated_at: null };
  }
});

app.put("/api/knowledge", async (req, reply) => {
  if (TOKEN && suppliedToken(req) !== TOKEN) {
    return reply.code(401).send({ error: "unauthorized" });
  }
  const text = (req.body as { text?: unknown } | null)?.text;
  if (typeof text !== "string") {
    return reply.code(400).send({ error: "expected { text: string }" });
  }
  if (text.length > KNOWLEDGE_MAX_CHARS) {
    return reply.code(413).send({ error: "knowledge too large" });
  }
  await fs.mkdir(path.dirname(KNOWLEDGE_PATH), { recursive: true });
  await fs.writeFile(KNOWLEDGE_PATH, text, "utf8");
  app.log.info({ chars: text.length }, "knowledge updated");
  return { ok: true, updated_at: new Date().toISOString() };
});

app.get("/panel", { websocket: true }, (socket) => {
  panels.add(socket);
  send(socket, { v: PROTOCOL_VERSION, seq, type: "sync", state });
  app.log.info({ panels: panels.size }, "panel connected");

  socket.on("close", () => {
    panels.delete(socket);
    app.log.info({ panels: panels.size }, "panel disconnected");
  });
  socket.on("error", () => panels.delete(socket));
});

app.get("/robot", { websocket: true }, (socket, req) => {
  const supplied =
    (req.query as Record<string, string | undefined>)?.token ??
    req.headers.authorization?.replace(/^Bearer\s+/i, "");
  if (TOKEN && supplied !== TOKEN) {
    app.log.warn({ ip: req.ip }, "robot rejected: bad token");
    socket.close(4401, "unauthorized");
    return;
  }

  robots.add(socket);
  app.log.info("robot connected");
  publish({ type: "robot.status", online: true, speaking: state.robot.speaking });

  socket.on("message", (data) => {
    let ev: DisplayEvent | null = null;
    try {
      ev = parseEvent(JSON.parse(data.toString()));
    } catch {
      ev = null;
    }
    if (!ev) {
      app.log.warn({ data: data.toString().slice(0, 200) }, "unparseable event");
      return;
    }
    app.log.info({ type: ev.type }, "event");
    publish(ev);
  });

  const onGone = () => {
    if (!robots.delete(socket)) return;
    if (robots.size === 0) {
      app.log.info("robot disconnected");
      publish({ type: "robot.status", online: false, speaking: false });
    }
  };
  socket.on("close", onGone);
  socket.on("error", onGone);
});

if (SERVE_STATIC) {
  await app.register(fastifyStatic, { root: DIST });
  // The panel is a single page; anything unmatched falls back to it.
  app.setNotFoundHandler((req, reply) => {
    if (req.raw.url?.startsWith("/api")) return reply.code(404).send({ error: "not_found" });
    return reply.sendFile("index.html");
  });
}

// Drop sockets that stop answering pings, so a slept laptop or a dropped wifi
// link doesn't linger as a phantom subscriber (or a phantom "robot online").
const alive = new WeakSet<WebSocket>();
const heartbeat = setInterval(() => {
  for (const s of [...panels, ...robots]) {
    if (!alive.has(s)) {
      s.terminate();
      continue;
    }
    alive.delete(s);
    s.ping();
  }
}, HEARTBEAT_MS);
app.addHook("onReady", async () => {
  app.websocketServer.on("connection", (socket: WebSocket) => {
    alive.add(socket);
    socket.on("pong", () => alive.add(socket));
  });
});
app.addHook("onClose", async () => clearInterval(heartbeat));

await app.listen({ port: PORT, host: HOST });
