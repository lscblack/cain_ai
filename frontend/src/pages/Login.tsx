import { useState, type FormEvent } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, ShieldCheck, Lock, Terminal } from "lucide-react";
import { Link } from "react-router-dom";

import { useAuth } from "@/lib/auth";
import { ApiError } from "@/types";

export function Login() {
  const { login, register, registrationOpen } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const firstRun = registrationOpen;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (firstRun) await register(email, password);
      else await login(email, password);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(
          err.detail === "invalid_credentials"
            ? "Invalid email or password."
            : err.detail === "network_error"
              ? "Cannot reach the backend."
              : err.detail,
        );
      } else {
        setError("Unexpected error.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-base px-4">
      {/* grid + ambient glow, matching the public terminal */}
      <div className="home-grid pointer-events-none absolute inset-0 opacity-40" aria-hidden="true" />
      <div
        className="pointer-events-none absolute left-1/2 top-1/3 h-[420px] w-[420px] -translate-x-1/2 rounded-full opacity-20 blur-[120px]"
        style={{ background: "var(--kai-accent)" }}
        aria-hidden="true"
      />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="relative w-full max-w-md border border-line bg-panel/90 backdrop-blur"
      >
        {/* top scanline accent */}
        <div className="relative h-0.5 w-full overflow-hidden bg-line" aria-hidden="true">
          <motion.div
            className="absolute inset-y-0 w-1/3"
            style={{ background: "linear-gradient(90deg, transparent, var(--kai-accent), transparent)" }}
            animate={{ x: ["-120%", "420%"] }}
            transition={{ duration: 3.2, repeat: Infinity, ease: "linear" }}
          />
        </div>

        <div className="p-7 sm:p-8">
          <div className="mb-6 flex items-center justify-between">
            <Link to="/" className="inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wider text-muted transition hover:text-ink">
              <ArrowLeft size={13} /> Public search
            </Link>
            <span className="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider text-muted">
              <Lock size={11} className="text-accent" /> Secure
            </span>
          </div>

          {/* brand */}
          <div className="mb-7 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center border border-accent/50 bg-panel text-accent shadow-[0_0_24px_rgba(229,72,77,0.18)]">
              <ShieldCheck size={22} />
            </div>
            <div>
              <div className="font-mono text-lg font-semibold tracking-[0.3em]">KAI</div>
              <div className="kai-metadata mt-0.5">Knowledge • Analysis • Intelligence</div>
            </div>
          </div>

          <div className="mb-5 flex items-center gap-2 border-y border-line py-2 font-mono text-[11px] uppercase tracking-[0.2em] text-accent">
            <Terminal size={13} />
            {firstRun ? "Initialize operator" : "Operator access"}
          </div>

          <form onSubmit={onSubmit} className="space-y-3">
            <label className="block">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-muted">Operator ID</span>
              <input
                type="text"
                autoComplete="username"
                required
                placeholder="operator@local or a username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="min-h-11 w-full border border-line bg-panel-2 px-3 font-mono text-sm text-ink outline-none transition focus:border-accent placeholder:text-muted/50"
              />
            </label>
            <label className="block">
              <span className="mb-1 block font-mono text-[10px] uppercase tracking-wider text-muted">Passphrase</span>
              <input
                type="password"
                required
                minLength={firstRun ? 8 : 1}
                placeholder={firstRun ? "Choose a password (min 8)" : "••••••••"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="min-h-11 w-full border border-line bg-panel-2 px-3 font-mono text-sm text-ink outline-none transition focus:border-accent placeholder:text-muted/50"
              />
            </label>

            {error && (
              <div className="border px-3 py-2 font-mono text-xs" style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
                ✗ {error}
              </div>
            )}

            <button
              type="submit"
              disabled={busy}
              className="inline-flex min-h-11 w-full items-center justify-center gap-2 bg-accent px-4 font-mono text-xs font-semibold uppercase tracking-wider text-white transition hover:brightness-110 disabled:opacity-40"
            >
              {busy ? "AUTHENTICATING…" : firstRun ? "Create operator & enter" : "Authenticate"}
            </button>
          </form>

          <div className="mt-6 flex items-center justify-between border-t border-line pt-3 font-mono text-[10px] uppercase tracking-wider text-muted">
            <span>{firstRun ? "First run · open registration" : "Registration locked"}</span>
            <span className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--kai-verified)" }} /> system online
            </span>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
