import { useEffect, useState } from "react";
import { Images, RefreshCw } from "lucide-react";

import { api } from "@/lib/api";
import { AuthImg } from "@/components/AuthImg";

interface IndexedFace {
  face_id: string;
  crop_url: string | null;
  source_url: string | null;
  investigation_id: string | null;
  quality: number;
  platform: string | null;
  created_at: string | null;
}

const PAGE = 60;

export function FaceIndex() {
  const [faces, setFaces] = useState<IndexedFace[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);

  function load(o = offset) {
    api.get<{ total: number; faces: IndexedFace[] }>(`/intelligence/face/index-list?limit=${PAGE}&offset=${o}`)
      .then((r) => { setFaces(r.faces); setTotal(r.total); })
      .catch(() => { setFaces([]); setTotal(0); });
  }

  useEffect(() => { load(0); }, []);

  return (
    <div>
      <div className="mb-5 flex items-center gap-2">
        <Images size={18} className="text-muted" />
        <h1 className="text-lg font-semibold">Available Faces</h1>
        <span className="kai-metadata">· {total} indexed</span>
        <button onClick={() => load(offset)} className="ml-auto kai-metadata flex items-center gap-1 hover:text-ink">
          <RefreshCw size={13} /> refresh
        </button>
      </div>

      {total === 0 && (
        <div className="rounded-lg border border-line bg-panel p-6 text-sm text-muted">
          No faces indexed yet. Index some via <span className="font-mono">Faces → Detect</span>,
          <span className="font-mono"> Usernames → Index avatars</span>, or by crawling a source.
        </div>
      )}

      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8">
        {faces.map((f) => (
          <div key={f.face_id} className="overflow-hidden rounded-lg border border-line bg-panel">
            <div className="aspect-square w-full bg-panel-2">
              {f.crop_url ? (
                <AuthImg path={f.crop_url} className="h-full w-full object-cover" />
              ) : (
                <div className="flex h-full items-center justify-center kai-metadata">no crop</div>
              )}
            </div>
            <div className="p-2">
              {f.source_url ? (
                <a href={f.source_url.startsWith("http") ? f.source_url : undefined} target="_blank" rel="noreferrer" className="kai-metadata block truncate hover:text-ink">
                  {f.platform ? `${f.platform}` : f.source_url}
                </a>
              ) : (
                <span className="kai-metadata">—</span>
              )}
              <div className="kai-metadata">q {Math.round((f.quality ?? 0) * 100)}%</div>
            </div>
          </div>
        ))}
      </div>

      {total > PAGE && (
        <div className="mt-5 flex items-center justify-center gap-4">
          <button disabled={offset === 0} onClick={() => { const o = Math.max(0, offset - PAGE); setOffset(o); load(o); }} className="rounded-md border border-line px-3 py-1.5 text-sm disabled:opacity-40">Prev</button>
          <span className="kai-metadata">{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <button disabled={offset + PAGE >= total} onClick={() => { const o = offset + PAGE; setOffset(o); load(o); }} className="rounded-md border border-line px-3 py-1.5 text-sm disabled:opacity-40">Next</button>
        </div>
      )}
    </div>
  );
}
