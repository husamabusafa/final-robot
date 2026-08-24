import { useCallback, useEffect, useState } from "react";

/**
 * Knowledge editor at /admin. The text saved here is fetched by the robot at
 * startup and appended to its system instruction, so Rafed facts can be
 * updated without redeploying the Pi. Guarded by HSAFA_PANEL_TOKEN.
 */
export default function AdminKnowledge() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("hsafa_panel_token") ?? "",
  );
  const [authed, setAuthed] = useState(false);
  const [text, setText] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);

  const headers = useCallback(
    () => ({
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    }),
    [token],
  );

  const load = useCallback(async () => {
    setBusy(true);
    setStatus("");
    try {
      const res = await fetch("/api/knowledge", { headers: headers() });
      if (res.status === 401) {
        setAuthed(false);
        sessionStorage.removeItem("hsafa_panel_token");
        setStatus("Wrong token.");
        return;
      }
      const data = (await res.json()) as {
        text: string;
        updated_at: string | null;
      };
      setText(data.text);
      setUpdatedAt(data.updated_at);
      setAuthed(true);
      sessionStorage.setItem("hsafa_panel_token", token);
    } catch {
      setStatus("Could not reach the relay.");
    } finally {
      setBusy(false);
    }
  }, [headers, token]);

  useEffect(() => {
    if (token) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    setBusy(true);
    setStatus("");
    try {
      const res = await fetch("/api/knowledge", {
        method: "PUT",
        headers: headers(),
        body: JSON.stringify({ text }),
      });
      if (!res.ok) {
        setStatus(`Save failed (${res.status}).`);
        return;
      }
      const data = (await res.json()) as { updated_at: string };
      setUpdatedAt(data.updated_at);
      setStatus("Saved. The robot picks this up on its next startup.");
    } catch {
      setStatus("Could not reach the relay.");
    } finally {
      setBusy(false);
    }
  };

  if (!authed) {
    return (
      <div className="flex h-full items-center justify-center">
        <form
          className="flex w-80 flex-col gap-4 rounded-2xl border border-line bg-card p-6"
          onSubmit={(e) => {
            e.preventDefault();
            void load();
          }}
        >
          <h1 className="text-xl font-bold">Knowledge admin</h1>
          <input
            type="password"
            autoFocus
            placeholder="Panel token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            className="rounded-lg border border-line bg-ink-2 px-3 py-2 outline-none focus:border-c1"
          />
          {status && <p className="text-sm text-c8">{status}</p>}
          <button
            type="submit"
            disabled={busy || !token}
            className="rounded-lg bg-c1 px-3 py-2 font-bold text-ink disabled:opacity-40"
          >
            {busy ? "…" : "Open editor"}
          </button>
        </form>
      </div>
    );
  }

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-4 p-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">
          Extra robot <span className="gradient-text">knowledge</span>
        </h1>
        <a href="/" className="text-sm text-dim underline">
          back to screen
        </a>
      </div>
      <p className="text-sm text-dim">
        Appended to the robot&rsquo;s knowledge on top of the built-in
        rafed_knowledge.md (which stays as the offline fallback). On conflicts,
        the robot prefers what is written here.
        {updatedAt && (
          <>
            {" "}
            Last saved:{" "}
            <span className="numerals">
              {new Date(updatedAt).toLocaleString()}
            </span>
          </>
        )}
      </p>
      <textarea
        dir="auto"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={"# أرقام محدثة\nعدد الباصات اليوم: ..."}
        className="min-h-0 flex-1 resize-none rounded-2xl border border-line bg-card p-4 leading-relaxed outline-none focus:border-c1"
      />
      <div className="flex items-center gap-4">
        <button
          onClick={() => void save()}
          disabled={busy}
          className="rounded-lg bg-c1 px-6 py-2 font-bold text-ink disabled:opacity-40"
        >
          {busy ? "…" : "Save"}
        </button>
        <button
          onClick={() => void load()}
          disabled={busy}
          className="rounded-lg border border-line px-4 py-2 text-dim disabled:opacity-40"
        >
          Reload
        </button>
        {status && <span className="text-sm text-dim">{status}</span>}
      </div>
    </div>
  );
}
