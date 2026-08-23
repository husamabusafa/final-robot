/**
 * Wire contract between the robot, the relay and the panel.
 *
 * Imported by BOTH server/index.ts and the React client, so the state machine
 * exists exactly once: the relay uses `applyEvent` to keep the state it replays
 * to late joiners, and the panel uses the same function to fold incoming events
 * into its React state. They can never drift.
 */

export const PROTOCOL_VERSION = 1;

/** Hard ceiling on tiles in a dashboard -- more than this and nothing is readable. */
export const MAX_TILES = 6;

export const TILE_TYPES = ["kpi", "bar", "pie", "line", "table"] as const;
export type TileType = (typeof TILE_TYPES)[number];

export interface Tile {
  /** Stable identity so React never re-mounts (and re-animates) an existing tile. */
  id: string;
  type: TileType;
  title: string;
  /** Category / metric names. Parallel to `values` (or `textValues` for tables). */
  labels: string[];
  /** Numbers, for every type except `table`. */
  values: number[];
  /** Free text, `table` only. Parallel to `labels`. */
  textValues?: string[];
  /** Suffix shown after formatted numbers, e.g. "طالب", "%", "ريال". */
  unit?: string;
}

export type DisplayMode = "idle" | "dashboard" | "video";

export interface DisplayState {
  mode: DisplayMode;
  title: string;
  tiles: Tile[];
  video: { url: string; title: string } | null;
  robot: { online: boolean; speaking: boolean };
}

export const initialState: DisplayState = {
  mode: "idle",
  title: "",
  tiles: [],
  video: null,
  robot: { online: false, speaking: false },
};

/** Everything the robot can tell the screen to do. */
export type DisplayEvent =
  | { type: "dashboard.begin"; title: string }
  | { type: "dashboard.tile"; tile: Tile }
  | { type: "video.show"; url: string; title: string }
  | { type: "display.clear" }
  | { type: "robot.status"; online: boolean; speaking: boolean };

/** Relay -> panel. `sync` carries the whole state; the rest are incremental. */
export type ServerMessage =
  | { v: number; seq: number; type: "sync"; state: DisplayState }
  | ({ v: number; seq: number } & DisplayEvent);

/** Robot -> relay. */
export type ClientMessage = { v: number } & DisplayEvent;

/**
 * Fold one event into the state. Pure, and returns a new object only for the
 * parts that changed so React can bail out of untouched subtrees.
 */
export function applyEvent(state: DisplayState, ev: DisplayEvent): DisplayState {
  switch (ev.type) {
    case "dashboard.begin":
      return { ...state, mode: "dashboard", title: ev.title, tiles: [], video: null };

    case "dashboard.tile": {
      // A tile can arrive without a preceding begin (Gemini calling add_tile
      // cold); treat that as an implicit begin rather than dropping it.
      const tiles = [...(state.mode === "dashboard" ? state.tiles : []), ev.tile];
      return {
        ...state,
        mode: "dashboard",
        video: null,
        tiles: tiles.slice(-MAX_TILES),
      };
    }

    case "video.show":
      return { ...state, mode: "video", video: { url: ev.url, title: ev.title }, tiles: [] };

    case "display.clear":
      return { ...state, mode: "idle", title: "", tiles: [], video: null };

    case "robot.status":
      return { ...state, robot: { online: ev.online, speaking: ev.speaking } };

    default:
      return state;
  }
}

/** Narrow untrusted JSON into a DisplayEvent. Returns null if it isn't one. */
export function parseEvent(raw: unknown): DisplayEvent | null {
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  switch (o.type) {
    case "dashboard.begin":
      return { type: "dashboard.begin", title: String(o.title ?? "") };
    case "dashboard.tile": {
      const tile = parseTile(o.tile);
      return tile ? { type: "dashboard.tile", tile } : null;
    }
    case "video.show":
      if (!o.url) return null;
      return { type: "video.show", url: String(o.url), title: String(o.title ?? "") };
    case "display.clear":
      return { type: "display.clear" };
    case "robot.status":
      return { type: "robot.status", online: !!o.online, speaking: !!o.speaking };
    default:
      return null;
  }
}

function parseTile(raw: unknown): Tile | null {
  if (typeof raw !== "object" || raw === null) return null;
  const o = raw as Record<string, unknown>;
  const type = o.type as TileType;
  if (!TILE_TYPES.includes(type)) return null;
  const labels = Array.isArray(o.labels) ? o.labels.map(String) : [];
  if (labels.length === 0) return null;
  const values = Array.isArray(o.values) ? o.values.map(Number).map((n) => (Number.isFinite(n) ? n : 0)) : [];
  const textValues = Array.isArray(o.textValues) ? o.textValues.map(String) : undefined;
  return {
    id: String(o.id ?? `t${Date.now()}${Math.random().toString(36).slice(2, 6)}`),
    type,
    title: String(o.title ?? ""),
    labels,
    values,
    ...(textValues ? { textValues } : {}),
    ...(o.unit ? { unit: String(o.unit) } : {}),
  };
}
