import { motion } from "framer-motion";
import type { Tile } from "../../shared/protocol.ts";
import { colorAt, compact, withUnit } from "../format.ts";
import { useCountUp } from "./useCountUp.ts";

function Stat({ label, value, unit, index }: { label: string; value: number; unit?: string; index: number }) {
  const shown = useCountUp(value);
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ delay: 0.08 * index, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      className="flex min-w-0 flex-col items-center justify-center rounded-2xl border
                 border-line/70 bg-ink-2/70 px-3 py-4 text-center"
    >
      <div
        className="numerals gradient-text truncate text-[clamp(22px,2.6vw,44px)] font-black leading-none"
        style={{ backgroundImage: `linear-gradient(135deg, ${colorAt(index)}, #a78bfa)` }}
      >
        {withUnit(compact(shown), unit)}
      </div>
      <div className="mt-2 line-clamp-2 text-[clamp(11px,1vw,16px)] font-medium text-dim">
        {label}
      </div>
    </motion.div>
  );
}

/** Big animated numbers. The workhorse tile for "show me the figures". */
export function KpiTile({ tile }: { tile: Tile }) {
  const n = tile.labels.length;
  // Columns chosen so cards stay wide enough to read at any count up to 6.
  const cols = n <= 2 ? n : n <= 4 ? 2 : 3;
  return (
    <div
      className="grid h-full content-center gap-3"
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {tile.labels.map((label, i) => (
        <Stat key={label + i} label={label} value={tile.values[i] ?? 0} unit={tile.unit} index={i} />
      ))}
    </div>
  );
}
