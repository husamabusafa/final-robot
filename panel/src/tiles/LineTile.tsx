import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Tile } from "../../shared/protocol.ts";
import { compact } from "../format.ts";
import { ChartTooltip } from "./ChartTooltip.tsx";

/** Trend over time. Filled area reads as growth from across a room. */
export function LineTile({ tile }: { tile: Tile }) {
  const data = tile.labels.map((label, i) => ({ label, value: tile.values[i] ?? 0 }));
  const gid = `line-${tile.id}`;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 10, right: 4, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#5ea3f7" stopOpacity={0.55} />
            <stop offset="100%" stopColor="#5ea3f7" stopOpacity={0} />
          </linearGradient>
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
        <Tooltip content={<ChartTooltip unit={tile.unit} />} />
        <Area
          type="monotone"
          dataKey="value"
          stroke="#5ea3f7"
          strokeWidth={3}
          fill={`url(#${gid})`}
          animationDuration={1100}
          dot={{ r: 4, fill: "#070b16", stroke: "#5ea3f7", strokeWidth: 2.5 }}
          activeDot={{ r: 6, fill: "#5ea3f7" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
