import { useState } from "react";
import type { FormEvent } from "react";
import type { LoginPayload } from "@livingdash/ui-shared";

interface LoginScreenProps {
  busy?: boolean;
  error?: string | null;
  onLogin: (payload: LoginPayload) => Promise<void>;
}

export function LoginScreen({ busy = false, error, onLogin }: LoginScreenProps) {
  const [username, setUsername] = useState("operator");
  const [password, setPassword] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onLogin({ username, password });
  }

  return (
    <main className="grid min-h-screen place-items-center bg-[var(--ld-bg)] p-4">
      <div className="w-full max-w-sm rounded-xl border border-white/10 bg-[var(--ld-panel)] p-6 shadow-[var(--ld-shadow-soft)]">
        <p className="text-[11px] uppercase tracking-[0.22em] text-[var(--ld-text-secondary)]">LivingDash GRID</p>
        <h1 className="mt-2 text-2xl font-semibold text-[var(--ld-text-primary)]">Analyst sign in</h1>
        <p className="mt-2 text-sm text-[var(--ld-text-secondary)]">Session uses cookie auth via /api/auth/session and /api/auth/login.</p>
        <form className="mt-5 space-y-3" onSubmit={handleSubmit}>
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            placeholder="Username"
          />
          <input
            className="w-full rounded-md border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none focus:border-cyan-300/60"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Password"
          />
          {error ? <p className="rounded-md border border-rose-400/40 bg-rose-900/35 px-3 py-2 text-xs text-rose-100">{error}</p> : null}
          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-md border border-cyan-300/30 bg-cyan-900/40 px-3 py-2 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-800/50 disabled:opacity-50"
          >
            {busy ? "Signing in..." : "Enter cockpit"}
          </button>
        </form>
      </div>
    </main>
  );
}
