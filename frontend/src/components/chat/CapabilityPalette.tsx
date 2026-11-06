import { useEffect, useMemo, useState } from "react";
import {
  Terminal, Globe, Search, Radar, ShieldAlert, FolderSearch, Boxes, ChevronRight, Lock, Crown,
} from "lucide-react";
import { toolsApi, type ToolOperation } from "@/lib/tools";

/** One runnable capability surfaced in the deck. */
interface Cap {
  key: string;
  title: string;
  description: string;
  posture: string;
  group: string;
  needsRoot: boolean;
  needsAuth: boolean;
  params: ToolOperation["params"];
}

// Always-available builtins. Merged in if the inventory doesn't already expose
// them, so the palette is never empty even before the tool catalogue loads.
const CORE: Cap[] = [
  { key: "shell.run", title: "Run a command", description: "Run a terminal command and read its output", posture: "shell", group: "Shell", needsRoot: false, needsAuth: false, params: [] },
  { key: "web.search", title: "Search the web", description: "Search the web and return organized results", posture: "web", group: "Web", needsRoot: false, needsAuth: false, params: [] },
  { key: "web.open", title: "Open a page", description: "Open a URL and read its contents", posture: "web", group: "Web", needsRoot: false, needsAuth: false, params: [] },
  { key: "maps.find", title: "Find on map", description: "Find a place or POI and show it on a map with coordinates", posture: "map", group: "Web", needsRoot: false, needsAuth: false, params: [] },
];

const GROUP_ICON: Record<string, typeof Terminal> = {
  Shell: Terminal, Web: Globe, Recon: Radar, OSINT: Search,
  Exploit: ShieldAlert, Investigation: FolderSearch, Other: Boxes,
};

// Map a tool's raw category / operation posture to a friendly deck group.
function groupFor(categories: string[], posture: string): string {
  const c = (categories[0] || posture || "").toLowerCase();
  if (c.includes("recon") || c.includes("scan") || c.includes("network") || c.includes("enum")) return "Recon";
  if (c.includes("osint") || c.includes("intel")) return "OSINT";
  if (c.includes("web")) return "Web";
  if (c.includes("exploit") || c.includes("attack") || c.includes("payload")) return "Exploit";
  if (c.includes("invest") || c.includes("case")) return "Investigation";
  if (c.includes("shell") || c.includes("system")) return "Shell";
  return "Other";
}

/** Turn a capability into an editable natural-language prompt for the composer. */
export function scaffoldPrompt(cap: Cap): string {
  const base = (cap.description || cap.title).trim();
  if (cap.key === "shell.run") return "Run this command: <command>";
  if (cap.key === "web.search") return "Search the web for <query>";
  if (cap.key === "web.open") return "Open and summarize <url>";
  if (cap.key === "maps.find") return "Show me on a map: <place or nearby POI>";
  const req = cap.params.filter((p) => p.required);
  if (!req.length) return base;
  const slots = req.map((p) => `${p.name}: <${p.name}>`).join(", ");
  return `${base}\n(${slots})`;
}

const GROUP_ORDER = ["Shell", "Web", "Recon", "OSINT", "Exploit", "Investigation", "Other"];

export function CapabilityPalette({ onPick }: { onPick: (text: string) => void }) {
  const [caps, setCaps] = useState<Cap[]>(CORE);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    toolsApi.inventory()
      .then((inv) => {
        if (!alive) return;
        const seen = new Set(CORE.map((c) => c.key));
        const list: Cap[] = [...CORE];
        for (const t of inv.tools) {
          if (!t.installed) continue;
          for (const op of t.operations) {
            if (seen.has(op.key)) continue;
            seen.add(op.key);
            list.push({
              key: op.key,
              title: op.title || op.key,
              description: op.description || "",
              posture: op.posture,
              group: groupFor(t.categories, op.posture),
              needsRoot: op.needs_root,
              needsAuth: op.requires_authorization,
              params: op.params,
            });
          }
        }
        setCaps(list);
      })
      .catch(() => { /* keep CORE only */ })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const matched = needle
      ? caps.filter((c) =>
          c.title.toLowerCase().includes(needle) ||
          c.key.toLowerCase().includes(needle) ||
          c.description.toLowerCase().includes(needle))
      : caps;
    const by: Record<string, Cap[]> = {};
    for (const c of matched) (by[c.group] ||= []).push(c);
    return GROUP_ORDER
      .filter((g) => by[g]?.length)
      .map((g) => [g, by[g].sort((a, b) => a.title.localeCompare(b.title))] as const);
  }, [caps, q]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative mb-2">
        <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={loading ? "loading capabilities…" : "filter capabilities…"}
          className="w-full rounded border border-line bg-panel-2 py-1.5 pl-7 pr-2 text-xs outline-none focus:border-current"
          style={{ color: "inherit" }}
        />
      </div>
      <div className="min-h-0 flex-1 space-y-2 overflow-auto pr-0.5">
        {groups.length === 0 && (
          <div className="kai-metadata px-1 py-2">No capability matches “{q}”.</div>
        )}
        {groups.map(([group, items]) => {
          const Icon = GROUP_ICON[group] || Boxes;
          return (
            <div key={group}>
              <div className="mb-1 flex items-center gap-1.5 px-1">
                <Icon size={11} style={{ color: "var(--kai-hud)" }} />
                <span className="hud-mono text-[10px] uppercase tracking-wider" style={{ color: "var(--kai-hud)" }}>
                  {group}
                </span>
                <span className="kai-metadata">{items.length}</span>
              </div>
              <div className="space-y-0.5">
                {items.map((c) => (
                  <button
                    key={c.key}
                    onClick={() => onPick(scaffoldPrompt(c))}
                    title={`${c.key}${c.description ? ` — ${c.description}` : ""}`}
                    className="group flex w-full items-center gap-1.5 rounded border border-transparent px-1.5 py-1 text-left hover:border-line hover:bg-panel-2"
                  >
                    <ChevronRight size={11} className="shrink-0 text-muted group-hover:text-ink" />
                    <span className="truncate text-[12px]">{c.title}</span>
                    {c.needsAuth && <Lock size={10} className="shrink-0" style={{ color: "var(--kai-warn)" }} />}
                    {c.needsRoot && <Crown size={10} className="shrink-0" style={{ color: "var(--kai-accent)" }} />}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
