import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Loader2, AlertTriangle, RefreshCw } from "lucide-react";

/** Inline spinner used by page/content loaders. */
export function Spinner({ size = 16, label }: { size?: number; label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-muted">
      <Loader2 size={size} className="kai-spin" style={{ color: "var(--kai-hud)" }} />
      {label && <span className="kai-metadata">{label}</span>}
    </span>
  );
}

/** Full content-area loading state (prevents a blank page on first load). */
export function PageLoading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center py-16">
      <Spinner size={22} label={label} />
    </div>
  );
}

/** Error state with a Retry button. */
export function ErrorRetry({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <AlertTriangle size={22} style={{ color: "var(--kai-accent)" }} />
      <div className="text-sm" style={{ color: "var(--kai-accent)" }}>{error}</div>
      <button
        onClick={onRetry}
        className="flex items-center gap-2 rounded border border-line px-3 py-1.5 text-sm hover:bg-panel"
      >
        <RefreshCw size={14} /> Retry
      </button>
    </div>
  );
}

type AsyncState<T> = { loading: boolean; error: string | null; data: T | null };

/** Run an async loader on mount (and on dep change); exposes retry. */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<AsyncState<T>>({ loading: true, error: null, data: null });

  const run = useCallback(() => {
    let alive = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    fn()
      .then((data) => alive && setState({ loading: false, error: null, data }))
      .catch((e) => alive && setState({ loading: false, error: e?.message || "request_failed", data: null }));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(run, [run]);

  const retry = useCallback(() => {
    run();
  }, [run]);

  return { ...state, retry, setData: (d: T) => setState((s) => ({ ...s, data: d })) };
}

/** Renders loading / error+retry / content for an async slice. */
export function AsyncBoundary<T>({
  state,
  children,
  loadingLabel,
}: {
  state: { loading: boolean; error: string | null; data: T | null; retry: () => void };
  children: (data: T) => ReactNode;
  loadingLabel?: string;
}) {
  if (state.loading && state.data == null) return <PageLoading label={loadingLabel} />;
  if (state.error && state.data == null) return <ErrorRetry error={state.error} onRetry={state.retry} />;
  if (state.data == null) return <PageLoading label={loadingLabel} />;
  return <>{children(state.data)}</>;
}
