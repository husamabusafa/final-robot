import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Tile } from "../../shared/protocol.ts";
import { colorAt, compact } from "../format.ts";
import { ChartTooltip } from "./ChartTooltip.tsx";

/** Compare entities on one metric. Categories read right-to-left. */
export function BarTile({ tile }: { tile: Tile }) {
  const data = tile.labels.map((label, i) => ({ label, value: tile.values[i] ?? 0 }));
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: 4 }}>
        <defs>
          {data.map((_, i) => (
            <linearGradient key={i} id={`bar-${tile.id}-${i}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={colorAt(i)} stopOpacity={0.95} />
              <stop offset="100%" stopColor={colorAt(i)} stopOpacity={0.35} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke="#1e293b" vertical={false} />
        <XAxis
          dataKey="label"
          reversed
          tickLine={false}
          axisLine={false}
          interval={0}
          tick={{ fill: "#8b98a9", fontSize: 13, fontFamily: "Tajawal" }}
        />
        <YAxis
          orientation="right"
          tickLine={false}
          axisLine={false}
          width={58}
          tickFormatter={compact}
          tick={{ fill: "#8b98a9", fontSize: 12, fontFamily: "Tajawal" }}
        />
        <Tooltip
          cursor={{ fill: "rgba(94,163,247,0.08)" }}
          content={<ChartTooltip unit={tile.unit} />}
        />
        <Bar dataKey="value" radius={[10, 10, 4, 4]} minPointSize={4} animationDuration={900}>
          {data.map((_, i) => (
            <Cell key={i} fill={`url(#bar-${tile.id}-${i})`} stroke={colorAt(i)} strokeWidth={1} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
