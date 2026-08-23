import { useEffect, useRef, useState } from "react";
import {
  applyEvent,
  initialState,
  type DisplayEvent,
  type DisplayState,
  type ServerMessage,
} from "../shared/protocol.ts";

/**
 * Subscribes to the relay and folds incoming events into state.
 *
 * Same-origin by construction, so there is nothing to configure: in dev Vite
 * proxies /panel to the relay, in production Fastify serves this page itself.
 */

/**
 * Gemini uses parallel function calling: the tiles of one dashboard typically
 * arrive within milliseconds of each other. Without pacing, "build one by one"
 * collapses into a single pop. Live tiles therefore go through a reveal queue;
 * anything that replaces the screen wholesale (begin/clear/video) drops the
 * queue, and a `sync` (late joiner) always shows the full state at once.
 */
const REVEAL_MS = 650;

export function useDisplay(): { state: DisplayState; connected: boolean } {
  const [state, setState] = useState<DisplayState>(initialState);
  const [connected, setConnected] = useState(false);
  const seqRef = useRef(0);
  const queueRef = useRef<DisplayEvent[]>([]);
  const timerRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const applyNow = (ev: DisplayEvent) =>
      setState((s) => applyEvent(s, ev));

    const dropQueue = () => {
      queueRef.current = [];
      window.clearTimeout(timerRef.current);
      timerRef.current = undefined;
    };

    const drain = () => {
      timerRef.current = undefined;
      const next = queueRef.current.shift();
      if (next) applyNow(next);
      if (queueRef.current.length) {
        timerRef.current = window.setTimeout(drain, REVEAL_MS);
      }
    };

    const enqueueTile = (ev: DisplayEvent) => {
      queueRef.current.push(ev);
      if (timerRef.current === undefined) drain();
    };

    const handle = (ev: DisplayEvent) => {
      switch (ev.type) {
        case "dashboard.tile":
          enqueueTile(ev);
          break;
        case "robot.status":
          // Orthogonal to the screen content; must not disturb a reveal.
          applyNow(ev);
          break;
        default:
          // begin / clear / video replace the screen: pending tiles belong to
          // the previous dashboard (or are superseded), so drop them.
          dropQueue();
          applyNow(ev);
      }
    };
    let ws: WebSocket | null = null;
    let retryTimer: number | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/panel`);

      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
      };

      ws.onmessage = (e) => {
        let msg: ServerMessage;
        try {
          msg = JSON.parse(e.data as string);
        } catch {
          return;
        }

        if (msg.type === "sync") {
          seqRef.current = msg.seq;
          dropQueue();
          setState(msg.state);
          return;
        }

        // A gap means we missed an event; reconnecting is the cheapest correct
        // recovery since the relay replays full state on connect.
        if (msg.seq !== seqRef.current + 1) {
          ws?.close();
          return;
        }
        seqRef.current = msg.seq;
        handle(msg);
      };

      const reconnect = () => {
        setConnected(false);
        if (closed) return;
        // Cap backoff at 5s: this screen is unattended and must recover on its own.
        const delay = Math.min(5000, 300 * 2 ** attempt++);
        retryTimer = window.setTimeout(connect, delay);
      };
      ws.onclose = reconnect;
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      dropQueue();
      window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  return { state, connected };
}
