import { motion } from "framer-motion";
import type { Tile } from "../../shared/protocol.ts";
import { colorAt, compact, withUnit } from "../format.ts";

/**
 * Facts that aren't chartable -- platform names, sectors, qualitative pairs.
 * Falls back to formatted numbers when `textValues` is absent, so a mistakenly
 * numeric table still renders correctly instead of showing blanks.
 */
export function TableTile({ tile }: { tile: Tile }) {
  const rows = tile.labels.map((label, i) => ({
    label,
    value:
      tile.textValues?.[i] ??
      (tile.values[i] !== undefined ? withUnit(compact(tile.values[i]), tile.unit) : ""),
  }));

  return (
    <div className="flex h-full min-h-0 flex-col justify-center gap-2 overflow-hidden">
      {rows.map((row, i) => (
        <motion.div
          key={row.label + i}
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.07 * i, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
          className="flex min-w-0 items-center gap-3 rounded-xl border border-line/60
                     bg-ink-2/60 px-3 py-2.5"
        >
          <span className="h-6 w-1 shrink-0 rounded-full" style={{ background: colorAt(i) }} />
          <span className="min-w-0 flex-1 truncate text-[clamp(12px,1.1vw,18px)] font-bold text-fg/90">
            {row.label}
          </span>
          <span className="min-w-0 max-w-[55%] truncate text-[clamp(11px,1vw,16px)] font-medium text-dim">
            {row.value}
          </span>
        </motion.div>
      ))}
    </div>
  );
}
