import { full, withUnit } from "../format.ts";

type Payload = { name?: string; value?: number | string; payload?: { label?: string } };

/** One tooltip style for every chart type. */
export function ChartTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean;
  payload?: Payload[];
  label?: string | number;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0];
  const value = typeof point.value === "number" ? full(point.value) : String(point.value ?? "");
  return (
    <div className="rounded-xl border border-line bg-ink-2/95 px-3 py-2 text-sm shadow-xl backdrop-blur">
      <div className="font-bold text-fg">{String(label ?? point.payload?.label ?? point.name ?? "")}</div>
      <div className="numerals mt-0.5 font-black text-c1">{withUnit(value, unit)}</div>
    </div>
  );
}
