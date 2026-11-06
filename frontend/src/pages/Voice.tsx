import { useSearchParams } from "react-router-dom";
import { AudioLines, Cpu, History as HistoryIcon, Library as LibraryIcon, Mic, Speech, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { CloneVoice } from "@/components/voice/CloneVoice";
import { History } from "@/components/voice/History";
import { Library } from "@/components/voice/Library";
import { LiveStudio } from "@/components/voice/LiveStudio";
import { Models } from "@/components/voice/Models";
import { TtsStudio } from "@/components/voice/TtsStudio";

const TABS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: "library", label: "Voice Library", icon: LibraryIcon },
  { id: "clone", label: "Clone a Voice", icon: Mic },
  { id: "tts", label: "Text-to-Speech", icon: Speech },
  { id: "live", label: "Live Voice Changer", icon: AudioLines },
  { id: "history", label: "Generation History", icon: HistoryIcon },
  { id: "models", label: "Model Management", icon: Cpu },
];

export function Voice() {
  const [params, setParams] = useSearchParams();
  const [ttsVoice, setTtsVoice] = useState("");
  const tab = TABS.some((t) => t.id === params.get("tab")) ? params.get("tab")! : "library";
  const go = (id: string) => setParams({ tab: id });
  // These two hold work in progress (a recording, typed text), so they stay mounted once opened.
  const [opened, setOpened] = useState({ clone: tab === "clone", tts: tab === "tts" });
  useEffect(() => {
    if (tab === "clone" || tab === "tts") setOpened((o) => ({ ...o, [tab]: true }));
  }, [tab]);

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <AudioLines size={18} style={{ color: "var(--kai-hud)" }} />
        <h1 className="hud-mono hud-glow text-lg font-semibold" style={{ color: "var(--kai-hud)" }}>◢ Voice Intelligence</h1>
      </div>

      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => go(id)}
            className={`flex shrink-0 items-center gap-1 border-b-2 px-3 py-2 hud-mono text-xs ${tab === id ? "" : "border-transparent text-muted"}`}
            style={tab === id ? { color: "var(--kai-hud)", borderColor: "var(--kai-hud)" } : undefined}>
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>

      {tab === "library" && <Library onCreate={() => go("clone")} onUse={(id) => { setTtsVoice(id); go("tts"); }} />}
      {opened.clone && <div hidden={tab !== "clone"}><CloneVoice onCreated={() => go("library")} /></div>}
      {opened.tts && <div hidden={tab !== "tts"}><TtsStudio initialVoice={ttsVoice} active={tab === "tts"} /></div>}
      {tab === "live" && <LiveStudio />}
      {tab === "history" && <History />}
      {tab === "models" && <Models />}
    </div>
  );
}
