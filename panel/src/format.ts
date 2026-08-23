/** Latin digits with Arabic scale words -- the convention in Saudi dashboards. */
const nf = new Intl.NumberFormat("ar-SA-u-nu-latn", { maximumFractionDigits: 1 });
const nfInt = new Intl.NumberFormat("ar-SA-u-nu-latn", { maximumFractionDigits: 0 });

/** 740000 -> "740 ألف", 122000000 -> "122 مليون". Used for big numbers and axes. */
export function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${nf.format(n / 1e9)} مليار`;
  if (abs >= 1e6) return `${nf.format(n / 1e6)} مليون`;
  if (abs >= 1000) return `${nf.format(n / 1000)} ألف`;
  return nfInt.format(n);
}

/** Full precision with separators, for tooltips. */
export function full(n: number): string {
  return nfInt.format(n);
}

export function withUnit(text: string, unit?: string): string {
  if (!unit) return text;
  return unit === "%" ? `${text}%` : `${text} ${unit}`;
}

export const TILE_COLORS = [
  "#5ea3f7",
  "#a78bfa",
  "#22c55e",
  "#f59e0b",
  "#ec4899",
  "#06b6d4",
  "#14b8a6",
  "#ef4444",
];

export const colorAt = (i: number) => TILE_COLORS[i % TILE_COLORS.length];
