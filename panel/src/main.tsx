import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import AdminKnowledge from "./admin/AdminKnowledge.tsx";
import "./index.css";

if (new URLSearchParams(location.search).get("screen") === "1") {
  document.body.dataset.kiosk = "1";
}

// Single-page app served for every unmatched path; /admin is the editor.
const root = location.pathname.startsWith("/admin") ? (
  <AdminKnowledge />
) : (
  <App />
);
createRoot(document.getElementById("root")!).render(root);
