import { useEffect, useRef, useState } from "react";
import {
  applyEvent,
  initialState,
  type DisplayState,
  type ServerMessage,
} from "../shared/protocol.ts";

/**
 * Subscribes to the relay and folds incoming events into state.
 *
 * Same-origin by construction, so there is nothing to configure: in dev Vite
 * proxies /panel to the relay, in production Fastify serves this page itself.
 */
export function useDisplay(): { state: DisplayState; connected: boolean } {
  const [state, setState] = useState<DisplayState>(initialState);
  const [connected, setConnected] = useState(false);
  const seqRef = useRef(0);

  useEffect(() => {
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
        setState((s) => applyEvent(s, msg));
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
      window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);

  return { state, connected };
}
