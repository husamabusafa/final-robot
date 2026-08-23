import { motion } from "framer-motion";

/**
 * Two facts, one pixel budget: is this page connected to the relay, and is the
 * robot itself connected. Distinguishing them turns "the screen is stuck" into
 * an answerable question during a demo.
 */
export function StatusDot({ connected, robotOnline }: { connected: boolean; robotOnline: boolean }) {
  const color = !connected ? "#ef4444" : robotOnline ? "#22c55e" : "#f59e0b";
  const label = !connected ? "لا يوجد اتصال بالشاشة" : robotOnline ? "الروبوت متصل" : "الروبوت غير متصل";

  return (
    <div className="group fixed top-4 left-4 z-50 flex items-center gap-2" title={label}>
      <motion.span
        className="h-2.5 w-2.5 rounded-full"
        style={{ background: color }}
        animate={{ opacity: connected && robotOnline ? [0.55, 1, 0.55] : 1 }}
        transition={{ duration: 2.2, repeat: Infinity }}
      />
      <span className="text-[11px] text-dim opacity-0 transition-opacity group-hover:opacity-100">
        {label}
      </span>
    </div>
  );
}
