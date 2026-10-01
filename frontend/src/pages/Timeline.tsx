import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Clock } from "lucide-react";

import { api } from "@/lib/api";
import { investigationsApi } from "@/lib/investigations";
import type { InvestigationDetail } from "@/types";

interface Event {
  kind: string;
  at: string;
  label: string;
  source_url: string | null;
}

const KIND_COLOR: Record<string, string> = {
  entity_added: "var(--kai-muted)",
  evidence: "var(--kai-verified)",
  relationship: "var(--kai-warn)",
};

export function Timeline() {
  const [params, setParams] = useSearchParams();
  const [cases, setCases] = useState<InvestigationDetail[]>([]);
  const [selected, setSelected] = useState(params.get("investigation") ?? "");
  const [events, setEvents] = useState<Event[]>([]);

  useEffect(() => {
    investigationsApi.list().then(setCases).catch(() => setCases([]));
  }, []);

  useEffect(() => {
    if (!selected) return setEvents([]);
    api.get<{ events: Event[] }>(`/investigations/${selected}/timeline`)
      .then((r) => setEvents(r.events))
      .catch(() => setEvents([]));
  }, [selected]);

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Clock size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Timeline</h1>
        <select
          value={selected}
          onChange={(e) => {
            setSelected(e.target.value);
            setParams(e.target.value ? { investigation: e.target.value } : {});
          }}
          className="ml-auto rounded-md border border-line bg-panel px-3 py-1.5 text-sm"
        >
          <option value="">Select investigation…</option>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>{c.code} — {c.name}</option>
          ))}
        </select>
      </div>

      {!selected && <div className="text-sm text-muted">Choose an investigation to see its timeline.</div>}

      {selected && events.length === 0 && <div className="text-sm text-muted">No dated events yet.</div>}

      <div className="relative ml-3 border-l border-line pl-6">
        {events.map((e, i) => (
          <div key={i} className="relative mb-5">
            <span
              className="absolute -left-[31px] top-1 inline-block h-3 w-3 rounded-full border-2 border-base"
              style={{ background: KIND_COLOR[e.kind] ?? "var(--kai-muted)" }}
            />
            <div className="kai-metadata">{new Date(e.at).toLocaleString()}</div>
            <div className="text-sm">
              <span className="kai-metadata uppercase mr-2">{e.kind.replace("_", " ")}</span>
              {e.label}
            </div>
            {e.source_url && (
              <a href={e.source_url} target="_blank" rel="noreferrer" className="kai-metadata hover:text-ink" style={{ color: "var(--kai-warn)" }}>
                {e.source_url}
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
