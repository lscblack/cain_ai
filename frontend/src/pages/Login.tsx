import { useState, type FormEvent } from "react";
import { motion } from "framer-motion";
import { ArrowLeft, ShieldCheck } from "lucide-react";
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
    <div className="flex min-h-screen items-center justify-center bg-base px-4">
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="w-full max-w-sm rounded-lg border border-line bg-panel p-7"
      >
        <Link to="/" className="mb-5 inline-flex items-center gap-2 text-xs text-muted hover:text-ink"><ArrowLeft size={14} /> Public search</Link>
        <div className="mb-6">
          <div className="flex items-center gap-2 text-xl font-semibold tracking-wide">
            <ShieldCheck size={20} style={{ color: "var(--kai-verified)" }} /> KAI
          </div>
          <div className="kai-metadata mt-1">Knowledge • Analysis • Intelligence</div>
        </div>

        <h1 className="mb-4 text-sm text-muted">
          {firstRun ? "Create the operator account" : "Operator sign in"}
        </h1>

        <form onSubmit={onSubmit} className="space-y-3">
          <input
            type="text"
            autoComplete="username"
            required
            placeholder="operator@local or a username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-muted"
          />
          <input
            type="password"
            required
            minLength={firstRun ? 8 : 1}
            placeholder={firstRun ? "Choose a password (min 8)" : "Password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-muted"
          />
          {error && (
            <div className="rounded-md border px-3 py-2 text-xs" style={{ borderColor: "var(--kai-accent)", color: "var(--kai-accent)" }}>
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md py-2 text-sm font-medium text-ink transition-opacity disabled:opacity-50"
            style={{ background: "var(--kai-panel-2)", border: "1px solid var(--kai-border)" }}
          >
            {busy ? "…" : firstRun ? "Create operator & enter" : "Sign in"}
          </button>
        </form>
      </motion.div>
    </div>
  );
}
