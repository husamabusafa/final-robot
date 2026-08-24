import { motion } from "framer-motion";

/**
 * Full-screen web page (e.g. the Rafed planning dashboard), shown via
 * page.show. Only works for sites that allow framing -- no X-Frame-Options
 * DENY/SAMEORIGIN and no CSP frame-ancestors. The title chip is
 * pointer-events-none so the page stays fully clickable/scrollable.
 */
export function WebScreen({ url, title }: { url: string; title: string }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="relative h-full w-full bg-white"
    >
      <iframe
        title={title || "صفحة"}
        src={url}
        className="h-full w-full border-0"
        allow="fullscreen"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
      />
      {title && (
        <div
          className="pointer-events-none absolute bottom-6 right-6 rounded-full
                     border border-line bg-ink-2/85 px-5 py-2 text-base font-bold
                     text-fg shadow-2xl backdrop-blur-md"
        >
          {title}
        </div>
      )}
    </motion.div>
  );
}
