import { useEffect, useRef } from "react";
import { motion } from "framer-motion";

/** Normalise any YouTube URL shape into a no-cookie autoplay embed. */
export function toEmbed(url: string): string {
  try {
    const u = new URL(url);
    let id: string | null = null;
    if (u.hostname.includes("youtu.be")) id = u.pathname.slice(1);
    else if (u.searchParams.get("v")) id = u.searchParams.get("v");
    else {
      const m = u.pathname.match(/\/(embed|shorts)\/([\w-]{11})/);
      if (m) id = m[2];
    }
    if (!id) return url;
    const start = parseInt(u.searchParams.get("t") ?? "", 10);
    let src = `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0&enablejsapi=1&playsinline=1`;
    if (Number.isFinite(start) && start > 0) src += `&start=${start}`;
    return src;
  } catch {
    return url;
  }
}

export function VideoScreen({ url, title }: { url: string; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);

  // Autoplay is unreliable on first paint; nudge the player via the iframe API.
  useEffect(() => {
    const play = () =>
      ref.current?.contentWindow?.postMessage(
        '{"event":"command","func":"playVideo","args":""}',
        "*",
      );
    const timers = [1500, 3500].map((ms) => window.setTimeout(play, ms));
    return () => timers.forEach(window.clearTimeout);
  }, [url]);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="h-full w-full bg-black"
    >
      <iframe
        ref={ref}
        title={title || "فيديو"}
        src={toEmbed(url)}
        className="h-full w-full border-0"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
      />
    </motion.div>
  );
}
