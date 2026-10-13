import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Phone as PhoneIcon } from "lucide-react";

import { api } from "@/lib/api";
import type { PhoneIntelligence } from "@/types";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-line/60 py-1.5">
      <span className="kai-metadata uppercase">{label}</span>
      <span className="font-mono text-sm">{value ?? "—"}</span>
    </div>
  );
}

export function Phone() {
  const [number, setNumber] = useState("");
  const [region, setRegion] = useState("");
  const [result, setResult] = useState<PhoneIntelligence | null>(null);
  const [loading, setLoading] = useState(false);

  const [params] = useSearchParams();

  async function run(value: string, reg?: string) {
    if (!value.trim()) return;
    setLoading(true);
    try {
      setResult(await api.post<PhoneIntelligence>("/intelligence/phone", {
        number: value.trim(), region: (reg ?? region).trim() || undefined,
      }));
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const q = params.get("q");
    if (q) { setNumber(q); run(q); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    run(number);
  }

  const a = result?.analysis;

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <PhoneIcon size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="hud-mono hud-glow text-lg font-semibold" style={{ color: "var(--kai-hud)" }}>◢ Phone Intelligence</h1>
      </div>

      <form onSubmit={onSubmit} className="mb-6 flex gap-2">
        <input
          value={number}
          onChange={(e) => setNumber(e.target.value)}
          placeholder="+250788123456"
          className="flex-1 border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[color:var(--kai-hud)]"
        />
        <input
          value={region}
          onChange={(e) => setRegion(e.target.value.toUpperCase())}
          placeholder="Region (RW)"
          maxLength={2}
          className="w-28 border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[color:var(--kai-hud)]"
        />
        <button className="hud-mono border px-4 py-2 text-sm uppercase tracking-wider transition hover:brightness-125" style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>
          Analyze
        </button>
      </form>

      {loading && <div className="kai-metadata" style={{ color: "var(--kai-hud)" }}>Analyzing…</div>}

      {a && !loading && (
        <div className="grid gap-5 md:grid-cols-2">
          <div className="hud-panel hud-frame p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="hud-mono uppercase text-xs" style={{ color: "var(--kai-hud)" }}>◢ Analysis</span>
              <span
                className="kai-metadata uppercase"
                style={{ color: a.valid ? "var(--kai-verified)" : "var(--kai-accent)" }}
              >
                {a.parsed ? (a.valid ? "valid" : "invalid") : "unparseable"}
              </span>
            </div>
            {a.parsed ? (
              <>
                <Row label="E.164" value={a.e164} />
                <Row label="International" value={a.international} />
                <Row label="National" value={a.national} />
                <Row label="Country" value={a.country_code ? `+${a.country_code} (${a.region})` : "—"} />
                <Row label="Location" value={a.location} />
                <Row label="Carrier" value={a.carrier} />
                <Row label="Type" value={a.number_type} />
                <div className="mt-3">
                  <div className="kai-metadata mb-1 uppercase">Variants</div>
                  <div className="flex flex-wrap gap-1">
                    {a.variants.map((v) => (
                      <span key={v} className="rounded border border-line px-2 py-0.5 font-mono text-xs">
                        {v}
                      </span>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <div className="text-sm text-muted">Could not parse: {a.error}</div>
            )}
          </div>

          <div className="hud-panel hud-frame p-4">
            <div className="hud-mono mb-2 uppercase text-xs" style={{ color: "var(--kai-hud)" }}>
              ◢ Local matches ({result!.local_entity_matches.length})
            </div>
            {result!.local_entity_matches.length === 0 ? (
              <div className="text-sm text-muted">NO MATCH FOUND IN CURRENT INDEX</div>
            ) : (
              <div className="space-y-2">
                {result!.local_entity_matches.map((m) => (
                  <div key={m.id} className="flex justify-between rounded-md border border-line px-3 py-2">
                    <span className="text-sm">{m.value}</span>
                    <span className="kai-metadata uppercase">{m.type}</span>
                  </div>
                ))}
              </div>
            )}
            <div className="kai-metadata mt-4 border-t border-line pt-3" style={{ color: "var(--kai-warn)" }}>
              {result!.note}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
