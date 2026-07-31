import { useAuth } from "../context/AuthContext";

function ShieldMark() {
  return (
    <svg
      className="h-7 w-7"
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
  );
}

export default function Navbar() {
  const { user, logout } = useAuth();

  return (
    <header className="glass sticky top-0 z-10 border-b border-white/10">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
        <div className="flex items-center gap-3">
          <span className="text-cyan-400 drop-shadow-[0_0_10px_rgba(34,211,238,0.5)]">
            <ShieldMark />
          </span>
          <div className="leading-tight">
            <p className="text-sm font-semibold tracking-wide text-white">
              Cybercrime Triage <span className="text-cyan-400">AI</span>
            </p>
            <p className="text-[11px] uppercase tracking-[0.2em] text-slate-400">
              Multimodal Threat Intelligence
            </p>
          </div>
        </div>

        {user && (
          <div className="flex items-center gap-3">
            <div className="hidden items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 sm:flex">
              <span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]" />
              <span className="text-sm text-slate-200">{user.username}</span>
            </div>
            <button
              onClick={logout}
              className="glow-ring rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm text-slate-300 transition hover:border-cyan-400/40 hover:text-white"
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
