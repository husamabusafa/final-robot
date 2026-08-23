import { motion } from "framer-motion";
import type { ReactNode } from "react";

/**
 * Shared chrome for every tile. The entrance animation is keyed to mount, and
 * tiles are keyed by id upstream, so an existing tile never replays it when a
 * new one is appended.
 */
export function TileFrame({
  title,
  span,
  accent,
  children,
}: {
  title: string;
  span: number;
  accent: string;
  children: ReactNode;
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 28, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{
        layout: { duration: 0.35, ease: [0.22, 1, 0.36, 1] },
        duration: 0.45,
        ease: [0.22, 1, 0.36, 1],
      }}
      style={{ gridColumn: `span ${span}` }}
      className="relative flex min-h-0 flex-col overflow-hidden rounded-3xl border
                 border-line/80 bg-card/70 p-5 shadow-[0_18px_50px_-20px_rgba(0,0,0,0.9)]
                 backdrop-blur-xl"
    >
      {/* Accent hairline: gives each tile identity without adding chrome. */}
      <div
        className="absolute inset-x-0 top-0 h-px opacity-70"
        style={{ background: `linear-gradient(90deg, transparent, ${accent}, transparent)` }}
      />
      <div
        className="pointer-events-none absolute -top-24 right-0 h-48 w-48 rounded-full opacity-20 blur-3xl"
        style={{ background: accent }}
      />

      <h3 className="mb-3 shrink-0 text-[clamp(15px,1.35vw,22px)] font-bold text-fg/90">
        {title}
      </h3>
      <div className="relative min-h-0 flex-1">{children}</div>
    </motion.div>
  );
}
