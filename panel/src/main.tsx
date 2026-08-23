import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./index.css";

if (new URLSearchParams(location.search).get("screen") === "1") {
  document.body.dataset.kiosk = "1";
}

createRoot(document.getElementById("root")!).render(<App />);
