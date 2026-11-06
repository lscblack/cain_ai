import { useEffect, useState } from "react";

import { AsyncBoundary, useAsync } from "@/components/Async";
import { GenerationRow } from "@/components/voice/GenerationRow";
import { ErrorLine } from "@/components/voice/shared";
import { friendly, voiceApi, voiceError } from "@/lib/voice";

export function History() {
  const state = useAsync(friendly(() => voiceApi.generations(100).then((r) => r.generations)), []);
  const [error, setError] = useState<string | null>(null);
  const active = state.data?.some((g) => g.status === "queued" || g.status === "running");

  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => voiceApi.generations(100).then((r) => state.setData(r.generations)).catch(() => undefined), 1500);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      state.retry();
    } catch (e) {
      setError(voiceError(e));
    }
  }

  return (
    <div>
      <ErrorLine error={error} />
      <AsyncBoundary state={state} loadingLabel="Loading history…">
        {(rows) => rows.length === 0 ? (
          <div className="kai-metadata py-10 text-center">Nothing generated yet.</div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {rows.map((g) => (
              <GenerationRow key={g.id} g={g}
                onCancel={(id) => run(() => voiceApi.cancelGeneration(id))}
                onDelete={(id) => { if (confirm("Delete this generated audio?")) run(() => voiceApi.deleteGeneration(id)); }} />
            ))}
          </div>
        )}
      </AsyncBoundary>
    </div>
  );
}
