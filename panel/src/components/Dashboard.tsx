import { AnimatePresence, motion } from "framer-motion";
import type { Tile } from "../../shared/protocol.ts";
import { colorAt } from "../format.ts";
import { rowCount, spans } from "../layout.ts";
import { BarTile } from "../tiles/BarTile.tsx";
import { KpiTile } from "../tiles/KpiTile.tsx";
import { LineTile } from "../tiles/LineTile.tsx";
import { MapTile } from "../tiles/MapTile.tsx";
import { PieTile } from "../tiles/PieTile.tsx";
import { TableTile } from "../tiles/TableTile.tsx";
import { TileFrame } from "../tiles/TileFrame.tsx";

function TileBody({ tile }: { tile: Tile }) {
  switch (tile.type) {
    case "kpi":
      return <KpiTile tile={tile} />;
    case "bar":
      return <BarTile tile={tile} />;
    case "pie":
      return <PieTile tile={tile} />;
    case "line":
      return <LineTile tile={tile} />;
    case "table":
      return <TableTile tile={tile} />;
    case "map":
      return <MapTile tile={tile} />;
  }
}

export function Dashboard({ title, tiles }: { title: string; tiles: Tile[] }) {
  const cols = spans(tiles);
  const rows = rowCount(tiles);

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 px-8 pt-6 pb-4">
        <motion.h1
          layout="position"
          className="text-center text-[clamp(22px,2.4vw,40px)] font-black leading-tight"
        >
          <span className="gradient-text">{title || "لوحة العرض"}</span>
        </motion.h1>
        <motion.div
          initial={{ scaleX: 0 }}
          animate={{ scaleX: 1 }}
          transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
          className="mx-auto mt-3 h-px w-2/5 bg-gradient-to-l from-transparent via-c2 to-transparent"
        />
      </header>

      <div
        className="grid min-h-0 flex-1 gap-4 px-6 pb-6"
        style={{
          gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
          gridTemplateRows: `repeat(${rows}, minmax(0, 1fr))`,
        }}
      >
        {/* Keyed by tile id: appending a tile must never re-mount its siblings,
            which is what made the old polling screen re-animate everything. */}
        <AnimatePresence mode="popLayout">
          {tiles.map((tile, i) => (
            <TileFrame key={tile.id} title={tile.title} span={cols[i]} accent={colorAt(i)}>
              <TileBody tile={tile} />
            </TileFrame>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
}
