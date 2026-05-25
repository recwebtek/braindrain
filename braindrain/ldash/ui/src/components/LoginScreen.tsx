import { useState } from "react";
import type { FormEvent } from "react";
import type { LoginPayload } from "@/api";
import { BrandMark } from "@/components/ldash/BrandMark";

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
    <main className="flex min-h-screen items-center justify-center px-4 py-8">
      <div className="w-full max-w-md rounded-[12px] border border-white/10 bg-[linear-gradient(180deg,rgba(8,10,14,0.97),rgba(2,4,6,0.99))] p-6 shadow-[0_20px_48px_rgba(0,0,0,0.52)] backdrop-blur-md">
        <BrandMark size="lg" compact />
        <p className="mt-6 text-xs uppercase tracking-[0.22em] text-[color:var(--ld-text-muted)]">LivingDash access</p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-white">Sign in to the operator shell</h1>
        <p className="mt-2 text-sm leading-6 text-[color:var(--ld-text-soft)]">
          Session state comes from <code className="text-sky-200">/api/auth/session</code> and login posts to{" "}
          <code className="text-sky-200">/api/auth/login</code>.
        </p>

        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <label className="block space-y-2">
            <span className="text-sm font-medium text-slate-200">Username</span>
            <input
              className="w-full rounded-[8px] border border-white/10 bg-white/[0.03] px-4 py-3 text-white outline-none ring-0 transition focus:border-sky-300/45 focus:bg-white/[0.05]"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              autoComplete="username"
            />
          </label>

          <label className="block space-y-2">
            <span className="text-sm font-medium text-slate-200">Password</span>
            <input
              className="w-full rounded-[8px] border border-white/10 bg-white/[0.03] px-4 py-3 text-white outline-none ring-0 transition focus:border-sky-300/45 focus:bg-white/[0.05]"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>

          {error ? <p className="rounded-[8px] border border-rose-400/30 bg-rose-950/40 px-4 py-3 text-sm text-rose-100">{error}</p> : null}

          <button
            className="w-full rounded-[8px] border border-sky-300/30 bg-[linear-gradient(180deg,rgba(20,46,72,0.96),rgba(10,25,42,0.98))] px-4 py-3 font-semibold text-white transition hover:border-sky-200/45 hover:bg-[linear-gradient(180deg,rgba(24,56,88,0.98),rgba(12,32,52,1))] disabled:cursor-not-allowed disabled:opacity-60"
            type="submit"
            disabled={busy}
          >
            {busy ? "Signing in..." : "Enter LivingDash"}
          </button>
        </form>
      </div>
    </main>
  );
}
