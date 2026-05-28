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
    <main className="nexus-auth-wrap">
      <section className="nexus-auth-card" aria-label="Nexus login">
        <p className="nexus-eyebrow">NEXUS ACCESS</p>
        <h1>Authorize mission control</h1>
        <p className="nexus-auth-text">
          Session check uses <code>/api/auth/session</code>. Login posts credentials to <code>/api/auth/login</code> and receives an
          HTTP cookie session.
        </p>
        <form className="nexus-auth-form" onSubmit={handleSubmit}>
          <label>
            Username
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            Password
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error ? <p className="nexus-error">{error}</p> : null}
          <button type="submit" disabled={busy}>
            {busy ? "Signing in..." : "Enter NEXUS"}
          </button>
        </form>
      </section>
    </main>
  );
}
