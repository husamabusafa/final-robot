import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";

/**
 * Browsers only allow autoplay when muted (or after the user has interacted
 * with the page). So videos start muted; the first tap on the overlay unlocks
 * sound, and every video after that plays with audio from the start. The
 * presentation laptop can skip this entirely by launching Chrome with
 * --autoplay-policy=no-user-gesture-required.
 */
let soundUnlocked = false;

/** Normalise any YouTube URL shape into a no-cookie autoplay embed. */
export function toEmbed(url: string, muted: boolean): string {
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
    let src =
      `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0` +
      `&enablejsapi=1&playsinline=1${muted ? "&mute=1" : ""}`;
    if (Number.isFinite(start) && start > 0) src += `&start=${start}`;
    return src;
  } catch {
    return url;
  }
}

export function VideoScreen({ url, title }: { url: string; title: string }) {
  const ref = useRef<HTMLIFrameElement>(null);
  const [muted, setMuted] = useState(!soundUnlocked);

  const command = (func: string, args = "") =>
    ref.current?.contentWindow?.postMessage(
      JSON.stringify({ event: "command", func, args }),
      "*",
    );

  // Autoplay is unreliable on first paint; nudge the player via the iframe API.
  useEffect(() => {
    const timers = [1500, 3500].map((ms) =>
      window.setTimeout(() => command("playVideo"), ms),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [url]);

  const unmute = () => {
    soundUnlocked = true;
    command("unMute");
    command("setVolume", "100");
    command("playVideo");
    setMuted(false);
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="relative h-full w-full bg-black"
    >
      <iframe
        ref={ref}
        title={title || "فيديو"}
        src={toEmbed(url, muted)}
        className="h-full w-full border-0"
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share; fullscreen"
        allowFullScreen
        referrerPolicy="strict-origin-when-cross-origin"
      />
      {muted && (
        <motion.button
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          onClick={unmute}
          className="absolute bottom-8 left-1/2 -translate-x-1/2 cursor-pointer
                     rounded-full border border-line bg-ink-2/80 px-6 py-3
                     text-lg font-bold text-fg shadow-2xl backdrop-blur-md
                     hover:border-c1"
        >
          <span className="gradient-text">اضغط للتشغيل بالصوت</span>
        </motion.button>
      )}
    </motion.div>
  );
}
