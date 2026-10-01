import { useAuth } from "@/lib/auth";
import { Login } from "@/pages/Login";
import { Dashboard } from "@/pages/Dashboard";

export default function App() {
  const { operator, loading } = useAuth();

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-base">
        <span className="kai-metadata">INITIALIZING…</span>
      </div>
    );
  }

  return operator ? <Dashboard /> : <Login />;
}
