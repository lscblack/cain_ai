import { useCallback, useEffect, useState } from "react";
import { Boxes, Plus, Trash2, Save, Power } from "lucide-react";

import { toolsApi, type Skill, type SkillIn } from "@/lib/tools";

const inputCls = "rounded border border-line bg-panel px-2 py-1 text-xs outline-none focus:border-current";
const btnCls = "flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel disabled:opacity-40";

const EMPTY: SkillIn = { name: "", description: "", content: "", enabled: true };

export function Skills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [editing, setEditing] = useState<(SkillIn & { id?: string }) | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setSkills(await toolsApi.skills()); } catch (e: any) { setMsg(e?.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function openEdit(id: string) {
    try { const s = await toolsApi.getSkill(id); setEditing({ id: s.id, name: s.name, description: s.description, content: s.content_text || "", enabled: s.enabled }); }
    catch (e: any) { setMsg(e?.message); }
  }
  async function toggle(s: Skill) {
    try { await toolsApi.updateSkill(s.id, { enabled: !s.enabled }); load(); } catch (e: any) { setMsg(e?.message); }
  }
  async function del(s: Skill) {
    if (!confirm(`Delete skill '${s.name}'?`)) return;
    try { await toolsApi.deleteSkill(s.id); load(); } catch (e: any) { setMsg(e?.message); }
  }
  async function save() {
    if (!editing) return;
    if (!editing.name.trim() || !editing.content.trim()) { setMsg("Name and content are required."); return; }
    try {
      if (editing.id) await toolsApi.updateSkill(editing.id, editing);
      else await toolsApi.addSkill(editing);
      setEditing(null); load();
    } catch (e: any) { setMsg(e?.message || "save failed"); }
  }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Boxes size={18} style={{ color: "var(--kai-hud)" }} />
          <h1 className="text-lg font-semibold">Skills</h1>
        </div>
        <button className={btnCls} onClick={() => setEditing({ ...EMPTY })}><Plus size={12} /> new skill</button>
      </div>
      <p className="text-xs text-muted">
        Reusable playbooks that teach KAI how you want recurring tasks done. Enabled skills are injected
        into KAI's guidance every turn.
      </p>
      {msg && <div className="rounded border border-line bg-panel-2 px-3 py-2 text-xs text-muted">{msg}</div>}

      {editing && (
        <div className="hud-panel hud-frame space-y-2 p-4">
          <div className="flex items-center justify-between">
            <div className="hud-mono text-xs uppercase" style={{ color: "var(--kai-hud)" }}>◢ {editing.id ? "Edit skill" : "New skill"}</div>
            <div className="flex gap-1">
              <button className={btnCls} onClick={() => setEditing(null)}>cancel</button>
              <button className={btnCls} onClick={save}><Save size={12} /> save</button>
            </div>
          </div>
          <input value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} placeholder="name" className={`${inputCls} w-full`} />
          <input value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} placeholder="when to use it" className={`${inputCls} w-full`} />
          <textarea rows={10} value={editing.content} onChange={(e) => setEditing({ ...editing, content: e.target.value })} placeholder="the playbook / steps…" className={`${inputCls} w-full font-mono`} />
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" checked={editing.enabled ?? true} onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })} /> enabled
          </label>
        </div>
      )}

      <div className="grid gap-2">
        {skills.length === 0 && <div className="text-xs text-muted">No skills yet.</div>}
        {skills.map((s) => (
          <div key={s.id} className="hud-panel hud-frame p-3 text-xs">
            <div className="flex items-center justify-between">
              <div className="font-medium">{s.name}</div>
              <div className="flex gap-1">
                <button className={btnCls} onClick={() => toggle(s)}>
                  <Power size={11} style={{ color: s.enabled ? "var(--kai-verified)" : "var(--kai-muted)" }} /> {s.enabled ? "on" : "off"}
                </button>
                <button className={btnCls} onClick={() => openEdit(s.id)}><Save size={11} /> edit</button>
                <button className={btnCls} onClick={() => del(s)}><Trash2 size={11} /></button>
              </div>
            </div>
            {s.description && <div className="mt-1 text-muted">{s.description}</div>}
            <div className="mt-1 text-[11px] text-muted">{s.char_count} chars</div>
          </div>
        ))}
      </div>
    </div>
  );
}
