import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { AtSign, CheckCircle2, XCircle } from "lucide-react";

import { api } from "@/lib/api";
import type { EmailIntelligence } from "@/types";

function Signal({ label, present, value }: { label: string; present: boolean | null; value?: string | null }) {
  const color = present ? "var(--kai-verified)" : present === false ? "var(--kai-accent)" : "var(--kai-muted)";
  const Icon = present ? CheckCircle2 : XCircle;
  return (
    <div className="flex items-center justify-between border-b border-line/60 py-1.5">
      <span className="kai-metadata uppercase">{label}</span>
      <span className="flex items-center gap-2 text-sm">
        {value && <span className="font-mono text-xs text-muted">{value}</span>}
        <Icon size={15} style={{ color }} />
      </span>
    </div>
  );
}

export function Email() {
  const [email, setEmail] = useState("");
  const [checkDns, setCheckDns] = useState(true);
  const [result, setResult] = useState<EmailIntelligence | null>(null);
  const [loading, setLoading] = useState(false);

  const [params] = useSearchParams();

  async function run(value: string) {
    if (!value.trim()) return;
    setLoading(true);
    try {
      setResult(await api.post<EmailIntelligence>("/intelligence/email", {
        email: value.trim(), check_dns: checkDns,
      }));
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const q = params.get("q");
    if (q) { setEmail(q); run(q); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    run(email);
  }

  const a = result?.analysis;

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <AtSign size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="hud-mono hud-glow text-lg font-semibold" style={{ color: "var(--kai-hud)" }}>◢ Email Intelligence</h1>
      </div>

      <form onSubmit={onSubmit} className="mb-6 flex items-center gap-2">
        <input
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="person@example.com"
          className="flex-1 border border-line bg-panel px-3 py-2 text-sm outline-none focus:border-[color:var(--kai-hud)]"
        />
        <label className="flex items-center gap-1 kai-metadata">
          <input type="checkbox" checked={checkDns} onChange={(e) => setCheckDns(e.target.checked)} />
          DNS
        </label>
        <button className="hud-mono border px-4 py-2 text-sm uppercase tracking-wider transition hover:brightness-125" style={{ borderColor: "var(--kai-hud-dim)", color: "var(--kai-hud)" }}>
          Analyze
        </button>
      </form>

      {loading && <div className="kai-metadata" style={{ color: "var(--kai-hud)" }}>Checking signals…</div>}

      {a && !loading && (
        <div className="grid gap-5 md:grid-cols-2">
          <div className="hud-panel hud-frame p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="hud-mono uppercase text-xs" style={{ color: "var(--kai-hud)" }}>◢ Direct signals</span>
              <span
                className="kai-metadata uppercase"
                style={{ color: a.valid_format ? "var(--kai-verified)" : "var(--kai-accent)" }}
              >
                {a.valid_format ? "valid format" : "invalid format"}
              </span>
            </div>
            {a.valid_format && (
              <>
                <div className="flex justify-between border-b border-line/60 py-1.5">
                  <span className="kai-metadata uppercase">Local</span>
                  <span className="font-mono text-sm">{a.local}</span>
                </div>
                <div className="flex justify-between border-b border-line/60 py-1.5">
                  <span className="kai-metadata uppercase">Domain</span>
                  <span className="font-mono text-sm">{a.domain}</span>
                </div>
                {a.dns_checked ? (
                  <>
                    <Signal label="MX" present={a.has_mx} value={a.mx_records?.[0] ?? null} />
                    <Signal label="SPF" present={!!a.spf} />
                    <Signal label="DMARC" present={!!a.dmarc} />
                  </>
                ) : (
                  <div className="kai-metadata py-2">DNS not checked</div>
                )}
                <div className="mt-3">
                  <div className="kai-metadata mb-1 uppercase">Derived usernames (inferred)</div>
                  <div className="flex flex-wrap gap-1">
                    {a.derived_usernames.map((u) => (
                      <span key={u} className="rounded border border-line px-2 py-0.5 font-mono text-xs">
                        {u}
                      </span>
                    ))}
                  </div>
                </div>
                {a.gravatar_url && (
                  <a href={a.gravatar_url} target="_blank" rel="noreferrer" className="kai-metadata mt-3 block hover:text-ink">
                    Gravatar candidate ↗
                  </a>
                )}
              </>
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
