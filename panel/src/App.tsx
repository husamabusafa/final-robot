import { AnimatePresence, motion } from "framer-motion";
import { Dashboard } from "./components/Dashboard.tsx";
import { IdleScreen } from "./components/IdleScreen.tsx";
import { StatusDot } from "./components/StatusDot.tsx";
import { VideoScreen } from "./components/VideoScreen.tsx";
import { useDisplay } from "./useDisplay.ts";

export default function App() {
  const { state, connected } = useDisplay();

  return (
    <div className="h-full w-full">
      <StatusDot connected={connected} robotOnline={state.robot.online} />

      {/* One mode on screen at a time; the crossfade hides the swap. */}
      <AnimatePresence mode="wait">
        {state.mode === "video" && state.video ? (
          <motion.div key="video" className="h-full">
            <VideoScreen url={state.video.url} title={state.video.title} />
          </motion.div>
        ) : state.mode === "dashboard" && state.tiles.length > 0 ? (
          <motion.div
            key="dashboard"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="h-full"
          >
            <Dashboard title={state.title} tiles={state.tiles} />
          </motion.div>
        ) : (
          <motion.div key="idle" exit={{ opacity: 0 }} className="h-full">
            <IdleScreen />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
