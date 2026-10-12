import { useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";
import { X, Smartphone } from "lucide-react";

import { getToken } from "@/lib/api";

const PAIR_URL_KEY = "kai.pairUrl";

function defaultUrl(): string {
  // 1) explicit phone-facing backend URL from env (recommended)
  const pub = import.meta.env.VITE_PUBLIC_API_URL as string | undefined;
  if (pub && /^https?:\/\//.test(pub)) return pub.replace(/\/+$/, "");
  // 2) a previously used value
  try {
    const saved = localStorage.getItem(PAIR_URL_KEY);
    if (saved) return saved;
  } catch {
    /* ignore */
  }
  // 3) absolute VITE_API_URL if set
  const base = import.meta.env.VITE_API_URL as string | undefined;
  if (base && /^https?:\/\//.test(base)) return base.replace(/\/+$/, "");
  // 4) derive from how the dashboard is being viewed (LAN IP -> PC IP:8001)
  try {
    const h = window.location.hostname;
    if (h && h !== "localhost" && h !== "127.0.0.1") return `http://${h}:8001`;
  } catch {
    /* ignore */
  }
  return "";
}

/** "Pair mobile" modal: shows a QR encoding {u: backendUrl, t: token} that the
 *  KAI mobile app scans to configure its backend + session in one shot. */
export function PairMobile({ onClose }: { onClose: () => void }) {
  const [url, setUrl] = useState(defaultUrl);
  const [dataUrl, setDataUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const payload = useMemo(() => {
    const token = getToken();
    if (!token) return null;
    if (!/^https?:\/\//.test(url.trim())) return null;
    return JSON.stringify({ u: url.trim().replace(/\/+$/, ""), t: token });
  }, [url]);

  useEffect(() => {
    if (!payload) {
      setDataUrl(null);
      return;
    }
    QRCode.toDataURL(payload, { width: 320, margin: 1, errorCorrectionLevel: "M" })
      .then((d) => {
        setDataUrl(d);
        setError(null);
        try {
          localStorage.setItem(PAIR_URL_KEY, url.trim().replace(/\/+$/, ""));
        } catch {
          /* ignore */
        }
      })
      .catch(() => setError("Could not render QR."));
  }, [payload, url]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div
        className="relative z-10 w-full max-w-md rounded-lg border bg-panel p-5"
        style={{ borderColor: "var(--kai-border)" }}
      >
        <div className="mb-3 flex items-center justify-between">
          <span className="flex items-center gap-2 text-sm font-semibold">
            <Smartphone size={16} /> Pair mobile device
          </span>
          <button onClick={onClose} className="text-muted hover:text-ink">
            <X size={18} />
          </button>
        </div>

        <div className="kai-metadata mb-1 uppercase">Backend URL the phone will use</div>
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://your-machine.tailnet.ts.net"
          className="mb-3 w-full rounded-md border bg-panel-2 px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--kai-border)" }}
        />

        <div className="flex flex-col items-center">
          {dataUrl ? (
            <img
              src={dataUrl}
              alt="pairing QR"
              className="rounded bg-white p-2"
              width={240}
              height={240}
            />
          ) : (
            <div
              className="flex h-[240px] w-[240px] items-center justify-center rounded border text-center text-xs text-muted"
              style={{ borderColor: "var(--kai-border)" }}
            >
              {!getToken()
                ? "Log in first to generate a pairing code."
                : "Enter the phone-reachable backend URL above (https://…)."}
            </div>
          )}
          {error && (
            <div className="mt-2 text-xs" style={{ color: "var(--kai-accent)" }}>
              {error}
            </div>
          )}
        </div>

        <div className="kai-metadata mt-4 leading-relaxed" style={{ color: "var(--kai-warn)" }}>
          In the KAI app: <span className="text-ink">Scan QR from web</span>. The code carries your
          current session token — keep it private and regenerate (reopen) if it leaks. It expires
          when your session does.
        </div>
      </div>
    </div>
  );
}
