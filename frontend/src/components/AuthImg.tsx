import { useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000";
const cache = new Map<string, string>();

/** <img> for an authenticated backend image path (fetches with bearer -> blob URL). */
export function AuthImg({ path, alt, className, style }: { path: string; alt?: string; className?: string; style?: React.CSSProperties }) {
  const [src, setSrc] = useState<string | null>(cache.get(path) ?? null);

  useEffect(() => {
    let active = true;
    if (cache.has(path)) {
      setSrc(cache.get(path)!);
      return;
    }
    const token = localStorage.getItem("kai.token");
    fetch(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => (r.ok ? r.blob() : Promise.reject()))
      .then((b) => {
        const url = URL.createObjectURL(b);
        cache.set(path, url);
        if (active) setSrc(url);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [path]);

  if (!src) return <div className={className} style={{ ...style, background: "var(--kai-panel-2)" }} />;
  return <img src={src} alt={alt ?? ""} className={className} style={style} />;
}
