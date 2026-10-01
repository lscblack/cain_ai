import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { ReadinessResponse } from "@/types";

export function StatusIndicator() {
  const [ready, setReady] = useState<ReadinessResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const r = await api.get<ReadinessResponse>("/health/ready");
        if (active) {
          setReady(r);
          setFailed(false);
        }
      } catch {
        if (active) {
          setFailed(true);
          setReady(null);
        }
      }
    }
    poll();
    const id = setInterval(poll, 5000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const ok = !failed && ready?.ready;
  const color = ok ? "var(--kai-verified)" : "var(--kai-accent)";
  const label = failed
    ? "BACKEND UNREACHABLE"
    : ok
      ? "SYSTEM ONLINE"
      : "DEGRADED";

  return (
    <div className="flex items-center gap-2 kai-metadata" title={ready ? JSON.stringify(ready) : ""}>
      <span
        style={{ background: color, boxShadow: `0 0 8px ${color}` }}
        className="inline-block h-2 w-2 rounded-full"
      />
      <span style={{ color }}>{label}</span>
      {ready && (
        <span className="text-muted">
          db:{ready.db} redis:{ready.redis}
        </span>
      )}
    </div>
  );
}
