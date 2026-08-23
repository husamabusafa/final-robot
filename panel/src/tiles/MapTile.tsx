import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map as MlMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Tile } from "../../shared/protocol.ts";

/**
 * MapLibre + CARTO's dark basemap, so the tile blends into the dashboard
 * theme. No API key. Basemap tiles come from CARTO/OSM -- a map tile needs
 * internet, which the panel has by definition (it is served over the internet).
 *
 * The RTL plugin is self-hosted in public/ because the basemap's place labels
 * in Saudi Arabia are Arabic; a CDN copy is exactly the kind of thing that
 * fails on venue wifi.
 */
const STYLE_URL = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const DEFAULT_CENTER: [number, number] = [46.6753, 24.7136]; // Riyadh

let rtlStarted = false;
function ensureRtlPlugin(): void {
  // Best-effort and fire-and-forget: if the plugin fails, the map must still
  // render (labels degrade, pins and basemap are unaffected). Gating map
  // creation on this promise is how a plugin hiccup becomes a blank tile.
  if (rtlStarted) return;
  rtlStarted = true;
  try {
    void maplibregl
      .setRTLTextPlugin("/mapbox-gl-rtl-text.js", true)
      .catch((e) => console.warn("[map] RTL plugin failed:", e));
  } catch (e) {
    console.warn("[map] RTL plugin failed:", e);
  }
}

function markerElement(accent: string): HTMLElement {
  const el = document.createElement("div");
  el.style.cssText = `width:14px;height:14px;border-radius:50%;background:${accent};
    box-shadow:0 0 0 3px ${accent}44, 0 0 18px ${accent};border:2px solid #070b16;`;
  return el;
}

export function MapTile({ tile }: { tile: Tile }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    ensureRtlPlugin();

    let map: MlMap | null = null;
    try {
      const markers = tile.markers ?? [];
      const center: [number, number] =
        tile.center ??
        (markers[0] ? [markers[0].lng, markers[0].lat] : DEFAULT_CENTER);

      map = new maplibregl.Map({
        container,
        style: STYLE_URL,
        center,
        zoom: tile.zoom ?? (markers.length > 1 ? 4 : 12),
        attributionControl: { compact: true },
        // A presentation screen, not an editor: no accidental pans mid-demo.
        interactive: false,
        fadeDuration: 400,
      });
      mapRef.current = map;

      map.on("load", () => {
        markers.forEach((m, i) => {
          const marker = new maplibregl.Marker({
            element: markerElement(i === 0 ? "#5ea3f7" : "#a78bfa"),
          })
            .setLngLat([m.lng, m.lat])
            .addTo(map!);
          if (m.label) {
            marker.setPopup(
              new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 18 })
                .setText(m.label),
            );
            marker.togglePopup();
          }
        });

        if (markers.length > 1 && !tile.center) {
          const bounds = new maplibregl.LngLatBounds();
          markers.forEach((m) => bounds.extend([m.lng, m.lat]));
          map!.fitBounds(bounds, { padding: 70, duration: 1200, maxZoom: 12 });
        }
      });

      map.on("error", (e) => {
        console.warn("[map] error:", e?.error ?? e);
        setError("تعذّر تحميل الخريطة");
      });
    } catch (e) {
      console.warn("[map] init failed:", e);
      setError("تعذّر تحميل الخريطة");
    }

    // The tile mounts mid-layout-animation, so the container can briefly
    // report zero size; nudge a resize once the entrance settles.
    const resizeTimer = window.setTimeout(() => map?.resize(), 500);

    return () => {
      window.clearTimeout(resizeTimer);
      map?.remove();
      mapRef.current = null;
    };
    // Tiles are immutable once pushed; build the map once on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center text-dim">
        {error}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="h-full min-h-[200px] w-full overflow-hidden rounded-xl [&_.maplibregl-popup-content]:!bg-ink-2
                 [&_.maplibregl-popup-content]:!text-fg [&_.maplibregl-popup-content]:!font-sans
                 [&_.maplibregl-popup-content]:!text-sm [&_.maplibregl-popup-content]:!font-bold
                 [&_.maplibregl-popup-tip]:!border-t-ink-2"
    />
  );
}
