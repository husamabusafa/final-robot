import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { Tile } from "../../shared/protocol.ts";
import { colorAt, compact, withUnit } from "../format.ts";
import { ChartTooltip } from "./ChartTooltip.tsx";

/**
 * Breakdown / share. The total sits in the hole so the tile answers "how much
 * in total?" as well as "split how?".
 */
export function PieTile({ tile }: { tile: Tile }) {
  const data = tile.labels.map((label, i) => ({ label, value: tile.values[i] ?? 0 }));
  const total = data.reduce((a, d) => a + d.value, 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative min-h-0 flex-1">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={data}
              dataKey="value"
              nameKey="label"
              innerRadius="58%"
              outerRadius="88%"
              paddingAngle={2}
              stroke="#070b16"
              strokeWidth={3}
              animationDuration={900}
            >
              {data.map((_, i) => (
                <Cell key={i} fill={colorAt(i)} />
              ))}
            </Pie>
            <Tooltip content={<ChartTooltip unit={tile.unit} />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <div className="numerals gradient-text text-[clamp(18px,1.9vw,32px)] font-black leading-none">
            {withUnit(compact(total), tile.unit)}
          </div>
          <div className="text-[11px] font-medium text-dim">الإجمالي</div>
        </div>
      </div>
      <div className="mt-3 flex shrink-0 flex-wrap justify-center gap-x-4 gap-y-1">
        {data.map((d, i) => (
          <span key={d.label + i} className="flex items-center gap-1.5 text-[clamp(10px,0.9vw,14px)] text-dim">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: colorAt(i) }} />
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}
