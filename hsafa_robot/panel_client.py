"""WebSocket client that pushes presentation-screen events to the panel relay.

Design notes
------------
* Runs its own asyncio loop on a background thread, so `emit()` is safe to call
  from the vision loop, the Gemini tool handler, or anywhere else.
* `emit()` NEVER blocks and never raises. If the panel is unreachable the event
  is dropped on purpose -- `AppState` is the source of truth and a full snapshot
  is replayed on every (re)connect, so dropping beats queueing: no duplicates,
  no stale events arriving out of order, and no unbounded memory.
* Replaying the snapshot on connect also means the screen recovers correctly
  when the *relay* restarts, not just when the robot's link drops.
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Callable, Optional

try:
    import websockets
except ImportError:  # pragma: no cover - optional until the panel is used
    websockets = None  # type: ignore[assignment]

# Wire protocol version; must match panel/shared/protocol.ts
PROTOCOL_VERSION = 1

SnapshotFn = Callable[[], list[dict]]


class PanelClient:
    """Publisher side of the panel protocol."""

    def __init__(
        self,
        url: str,
        token: str = "",
        snapshot: Optional[SnapshotFn] = None,
        log: Callable[[str], None] = print,
    ) -> None:
        self._url = url
        self._token = token
        self._snapshot = snapshot
        self._log = log
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ws = None
        self._stop = threading.Event()
        self._connected = threading.Event()

    # --- public API ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self) -> None:
        if websockets is None:
            self._log("  WARNING: panel disabled -- pip install websockets")
            return
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="panel-client", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        loop, ws = self._loop, self._ws
        if loop is not None and ws is not None:
            asyncio.run_coroutine_threadsafe(ws.close(), loop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def emit(self, event: dict) -> None:
        """Fire-and-forget one protocol event."""
        loop, ws = self._loop, self._ws
        if loop is None or ws is None or not self._connected.is_set():
            return
        payload = json.dumps({"v": PROTOCOL_VERSION, **event}, ensure_ascii=False)
        try:
            asyncio.run_coroutine_threadsafe(self._send(payload), loop)
        except RuntimeError:
            pass  # loop shutting down

    # --- internals ---------------------------------------------------------

    async def _send(self, payload: str) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send(payload)
        except Exception:
            self._connected.clear()

    def _full_url(self) -> str:
        if not self._token:
            return self._url
        sep = "&" if "?" in self._url else "?"
        return f"{self._url}{sep}token={self._token}"

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_forever())
        finally:
            self._loop.close()

    async def _connect_forever(self) -> None:
        backoff = 1.0
        announced = False
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._full_url(),
                    ping_interval=20,
                    ping_timeout=20,
                    open_timeout=10,
                    close_timeout=5,
                    max_queue=32,
                ) as ws:
                    self._ws = ws
                    self._connected.set()
                    backoff = 1.0
                    if not announced:
                        self._log(f"[panel] connected to {self._url}")
                        announced = True
                    await self._replay_snapshot()
                    # The relay never talks back; this just parks until close.
                    async for _ in ws:
                        pass
            except Exception as e:
                if announced:
                    self._log(f"[panel] disconnected ({type(e).__name__}); retrying")
                    announced = False
            finally:
                self._connected.clear()
                self._ws = None

            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15.0)

    async def _replay_snapshot(self) -> None:
        if self._snapshot is None:
            return
        try:
            events = self._snapshot()
        except Exception as e:
            self._log(f"[panel] snapshot failed: {e}")
            return
        for ev in events:
            await self._send(
                json.dumps({"v": PROTOCOL_VERSION, **ev}, ensure_ascii=False)
            )
