import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { api, getToken, setToken } from "@/lib/api";
import type { Operator, TokenResponse } from "@/types";

interface AuthState {
  operator: Operator | null;
  loading: boolean;
  registrationOpen: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [operator, setOperator] = useState<Operator | null>(null);
  const [loading, setLoading] = useState(true);
  const [registrationOpen, setRegistrationOpen] = useState(false);

  async function refreshRegistration() {
    try {
      const s = await api.get<{ registration_open: boolean }>("/auth/registration-status");
      setRegistrationOpen(s.registration_open);
    } catch {
      setRegistrationOpen(false);
    }
  }

  async function loadMe() {
    if (!getToken()) {
      setOperator(null);
      return;
    }
    try {
      setOperator(await api.get<Operator>("/auth/me"));
    } catch {
      setToken(null);
      setOperator(null);
    }
  }

  useEffect(() => {
    (async () => {
      await Promise.all([loadMe(), refreshRegistration()]);
      setLoading(false);
    })();
  }, []);

  async function login(email: string, password: string) {
    const res = await api.post<TokenResponse>("/auth/login", { email, password });
    setToken(res.access_token);
    await loadMe();
  }

  async function register(email: string, password: string) {
    const res = await api.post<TokenResponse>("/auth/register", { email, password });
    setToken(res.access_token);
    await Promise.all([loadMe(), refreshRegistration()]);
  }

  function logout() {
    setToken(null);
    setOperator(null);
  }

  return (
    <AuthContext.Provider
      value={{ operator, loading, registrationOpen, login, register, logout }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
