// Global in-flight request tracker — lets a single top progress bar reflect
// loading on every page without each page wiring it up.
type Listener = (count: number) => void;

let count = 0;
const listeners = new Set<Listener>();

function emit() {
  for (const l of listeners) l(count);
}

export function beginRequest(): void {
  count += 1;
  emit();
}

export function endRequest(): void {
  count = Math.max(0, count - 1);
  emit();
}

export function getActivity(): number {
  return count;
}

export function subscribeActivity(l: Listener): () => void {
  listeners.add(l);
  l(count);
  return () => {
    listeners.delete(l);
  };
}

/** Wrap any async op so it counts toward the global activity indicator. */
export async function tracked<T>(fn: () => Promise<T>): Promise<T> {
  beginRequest();
  try {
    return await fn();
  } finally {
    endRequest();
  }
}
