import { useEffect, useState } from "react";
import { chatApi, type ActiveRun } from "@/lib/chat";

// One shared poller for every component that wants to know what KAI is doing.
let runs: ActiveRun[] = [];
const subs = new Set<(r: ActiveRun[]) => void>();
let timer: number | null = null;

async function poll() {
  try { runs = await chatApi.active(); } catch { return; }
  subs.forEach((f) => f(runs));
}

/** Turns KAI is generating right now (server-side, so it survives page changes). */
export function useActiveRuns(intervalMs = 2500): ActiveRun[] {
  const [state, setState] = useState<ActiveRun[]>(runs);
  useEffect(() => {
    subs.add(setState);
    if (timer === null) {
      poll();
      timer = window.setInterval(poll, intervalMs);
    }
    return () => {
      subs.delete(setState);
      if (subs.size === 0 && timer !== null) { clearInterval(timer); timer = null; }
    };
  }, [intervalMs]);
  return state;
}

export const pollActiveNow = poll;
