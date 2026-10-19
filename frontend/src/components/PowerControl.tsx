import { useCallback, useEffect, useState } from "react";
import { Power, Play, Loader2 } from "lucide-react";

import { api } from "@/lib/api";

interface PowerState {
  running: boolean;
  worker_active: boolean;
  model_loaded: boolean;
  stopped_flag: boolean;
}

/** Header control to stop/start KAI's background engine (crawl/discovery worker
 *  + local model). The API/UI stay up so it can be toggled again. */
export function PowerControl() {
  const [state, setState] = useState<PowerState | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<PowerState>("/system/power").then(setState).catch(() => {});
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  async function toggle() {
    if (busy || !state) return;
    if (state.running) {
      const ok = window.confirm(
        "Stop KAI?\n\nThis halts all background crawling/discovery and unloads the " +
        "local model from memory. The app stays usable — Start brings it back.",
      );
      if (!ok) return;
    }
    setBusy(true);
    try {
      await api.post(state.running ? "/system/power/stop" : "/system/power/start");
    } catch {
      /* surfaced by reload */
    }
    setBusy(false);
    load();
  }

  const running = state?.running ?? true;
  const color = running ? "var(--kai-verified)" : "var(--kai-accent)";
  const label = state == null ? "…" : running ? "Stop KAI" : "Start KAI";

  return (
    <button
      onClick={toggle}
      disabled={busy || state == null}
      title={
        running
          ? "KAI is running — click to stop background engine + unload model"
          : "KAI is stopped — click to start"
      }
      className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel disabled:opacity-50"
      style={{ color }}
    >
      {busy ? (
        <Loader2 size={14} className="kai-spin" />
      ) : running ? (
        <Power size={14} />
      ) : (
        <Play size={14} />
      )}
      {label}
    </button>
  );
}
