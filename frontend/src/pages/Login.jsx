import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    setError("");
    if (!username.trim() || !password.trim()) {
      setError("Enter any username and password to continue (demo mode).");
      return;
    }
    try {
      login(username);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="cyber-bg flex min-h-screen items-center justify-center px-4 py-10">
      <div className="w-full max-w-md">
        {/* Brand */}
        <div className="mb-8 flex flex-col items-center text-center">
          <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl border border-cyan-400/30 bg-cyan-400/10 text-cyan-400 shadow-[0_0_30px_rgba(34,211,238,0.25)]">
            <svg
              className="h-9 w-9"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="m9 12 2 2 4-4" />
            </svg>
          </div>
          <h1 className="text-2xl font-semibold text-white">
            Cybercrime Triage <span className="text-cyan-400">AI</span>
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Secure analyst console — sign in to file an incident
          </p>
        </div>

        {/* Card */}
        <form onSubmit={handleSubmit} className="glass rounded-2xl p-6 sm:p-7">
          {error && (
            <div className="mb-4 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-sm text-rose-200">
              {error}
            </div>
          )}

          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Analyst ID
          </label>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="e.g. officer.rao"
            className="glow-ring mb-4 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500"
          />

          <label className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-slate-400">
            Passphrase
          </label>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            className="glow-ring mb-5 w-full rounded-lg border border-white/10 bg-ink-900/60 px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500"
          />

          <button
            type="submit"
            className="glow-ring w-full rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 px-4 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_24px_rgba(34,211,238,0.35)] transition hover:brightness-110"
          >
            Enter Console →
          </button>

          <p className="mt-4 text-center text-xs text-slate-500">
            Demo mode — any username and password will sign you in.
          </p>
        </form>
      </div>
    </div>
  );
}
