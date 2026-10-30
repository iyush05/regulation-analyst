import { useState } from "react";
import { api, ApiError, setToken } from "../api/client";

export function Login({ onLogin }: { onLogin: () => void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setToken(value.trim());
    try {
      await api.companies();
      onLogin();
    } catch (e) {
      setToken("");
      setError(
        e instanceof ApiError && e.status === 401
          ? "That access token was not accepted."
          : `Could not reach the API: ${(e as Error).message}`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} className="card">
        <h1>Regulation Analyst</h1>
        <p className="muted">
          Enter the access token set as <code>REGULATION_API_TOKEN</code> on the API server.
        </p>
        <label>
          Access token
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || !value.trim()}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
