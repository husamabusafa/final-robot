import type { Tile } from "../shared/protocol.ts";

/**
 * Deterministic layout so the dashboard looks composed at every tile count --
 * a single tile fills the screen, three sit in one balanced row, six tile
 * cleanly. Nothing is left to chance, and nothing depends on what Gemini sends.
 *
 * The grid is 6 columns wide; these are the column spans per tile count:
 */
const SLOTS: Record<number, number[]> = {
  1: [6],
  2: [3, 3],
  3: [2, 2, 2],
  4: [3, 3, 3, 3],
  5: [2, 2, 2, 3, 3],
  6: [2, 2, 2, 2, 2, 2],
};

/** How much a tile benefits from extra width. */
function widthAppetite(tile: Tile): number {
  switch (tile.type) {
    case "line":
      return 4;
    case "kpi":
      return tile.labels.length >= 4 ? 3 : 1;
    case "table":
      return 2;
    case "bar":
      return tile.labels.length >= 5 ? 2 : 1;
    case "pie":
      return 0;
  }
}

/**
 * Column span per tile, in tile order. The wider slots for a given count go to
 * the tiles that actually want them, without reordering the DOM (reordering
 * would re-trigger entrance animations).
 */
export function spans(tiles: Tile[]): number[] {
  const slots = SLOTS[tiles.length] ?? SLOTS[6];
  const byAppetite = tiles
    .map((tile, i) => ({ i, appetite: widthAppetite(tile) }))
    .sort((a, b) => b.appetite - a.appetite || a.i - b.i);
  const widest = [...slots].sort((a, b) => b - a);

  const out = new Array<number>(tiles.length).fill(1);
  byAppetite.forEach((entry, rank) => {
    out[entry.i] = widest[rank] ?? 2;
  });
  return out;
}

/** Rows needed, so the grid can divide the available height evenly. */
export function rowCount(tiles: Tile[]): number {
  const total = spans(tiles).reduce((a, b) => a + b, 0);
  return Math.max(1, Math.ceil(total / 6));
}
