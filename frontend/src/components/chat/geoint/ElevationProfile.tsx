import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export interface LatLon { lat: number; lon: number }
interface ElevResp { ok: boolean; results?: { lat: number; lon: number; elevation_m: number | null }[]; reason?: string }

export function elevationQuery(points: LatLon[]): string {
  return "/geoint/elevation?points=" + encodeURIComponent(points.map((p) => `${p.lat.toFixed(5)},${p.lon.toFixed(5)}`).join("|"));
}

/** Fetch a single point's elevation in metres; null on any failure. */
export async function fetchPointElevation(p: LatLon): Promise<number | null> {
  try {
    const r = await api.get<ElevResp>(elevationQuery([p]));
    const v = r?.ok ? r.results?.[0]?.elevation_m : null;
    return typeof v === "number" ? v : null;
  } catch { return null; }
}

/** Evenly pick up to n points (incl. first and last) from a [lat, lon] polyline. */
export function samplePath(path: [number, number][], n = 30): LatLon[] {
  if (path.length === 0) return [];
  const k = Math.min(n, path.length);
  if (k === 1) return [{ lat: path[0][0], lon: path[0][1] }];
  return Array.from({ length: k }, (_, i) => {
    const p = path[Math.round((i * (path.length - 1)) / (k - 1))];
    return { lat: p[0], lon: p[1] };
  });
}

export function ElevationProfile({ points }: { points: LatLon[] }) {
  const [elev, setElev] = useState<number[] | null>(null);
  const key = points.map((p) => `${p.lat},${p.lon}`).join("|");

  useEffect(() => {
    let live = true;
    setElev(null);
    if (points.length < 2) return;
    api.get<ElevResp>(elevationQuery(points))
      .then((r) => {
        if (!live) return;
        const vals = r?.ok && r.results ? r.results.map((x) => x.elevation_m) : [];
        const nums = vals.filter((v): v is number => typeof v === "number");
        setElev(nums.length >= 2 ? nums : null);
      })
      .catch(() => { if (live) setElev(null); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!elev) return null;
  const min = Math.min(...elev), max = Math.max(...elev);
  let gain = 0;
  for (let i = 1; i < elev.length; i++) if (elev[i] > elev[i - 1]) gain += elev[i] - elev[i - 1];
  const W = 160, H = 28, span = max - min || 1;
  const pts = elev.map((v, i) => `${((i / (elev.length - 1)) * W).toFixed(1)},${(H - 2 - ((v - min) / span) * (H - 4)).toFixed(1)}`).join(" ");

  return (
    <div className="flex items-center gap-2 px-2 py-1 text-[10px]" style={{ color: "var(--kai-muted)" }}>
      <span className="kai-metadata">elevation:</span>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Elevation profile">
        <polyline points={pts} fill="none" stroke="#30a46c" strokeWidth={1.5} />
      </svg>
      <span className="hud-mono">min {Math.round(min)} m · max {Math.round(max)} m · +{Math.round(gain)} m</span>
    </div>
  );
}

/** Popup line: fetches the point's elevation on mount (i.e. when the popup opens). */
export function PointElevation({ lat, lon }: LatLon) {
  const [m, setM] = useState<number | null>(null);
  useEffect(() => {
    let live = true;
    fetchPointElevation({ lat, lon }).then((v) => { if (live) setM(v); });
    return () => { live = false; };
  }, [lat, lon]);
  return m == null ? null : <div>Elevation: {Math.round(m)} m</div>;
}
