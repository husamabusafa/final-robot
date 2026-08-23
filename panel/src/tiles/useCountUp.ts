import { useEffect, useState } from "react";

/**
 * Counts from 0 to `target` once, on mount. Deliberately not reactive to
 * `target` changes: tiles are immutable once pushed, and re-running would make
 * the dashboard flicker whenever a sibling tile arrives.
 */
export function useCountUp(target: number, durationMs = 1100): number {
  const [value, setValue] = useState(0);

  useEffect(() => {
    if (!Number.isFinite(target)) return;
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min((now - start) / durationMs, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(target * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
      else setValue(target);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return value;
}
