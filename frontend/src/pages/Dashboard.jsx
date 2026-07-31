import { useRef, useState } from "react";
import Navbar from "../components/Navbar";
import { analyzeIncident } from "../api/client";

const SAMPLE =
  "Victim received a call from someone posing as a bank official asking to complete KYC. They shared an OTP and ₹48,000 was debited via UPI to an unknown account.";

export default function Dashboard() {
  const [query, setQuery] = useState("");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [dragging, setDragging] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  const acceptFile = (f) => {
    if (!f) return;
    if (!f.type.startsWith("image/")) {
      setError("Please attach an image file (screenshot).");
      return;
    }
    setError("");
    setFile(f);
    setPreview(URL.createObjectURL(f));
  };

  const clearFile = () => {
    if (preview) URL.revokeObjectURL(preview);
    setFile(null);
    setPreview(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragging(false);
    acceptFile(e.dataTransfer.files?.[0]);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!query.trim() && !file) {
      setError("Provide a complaint description or attach a screenshot (or both).");
      return;
    }
    setLoading(true);
    setResult(null);
    try {
      const data = await analyzeIncident({ query, file });
      setResult(data);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="cyber-bg min-h-screen">
      <Navbar />

      <main className="mx-auto max-w-6xl px-5 py-8">
        <div className="mb-6">
          <h2 className="text-xl font-semibold text-white">File an Incident</h2>
          <p className="mt-1 text-sm text-slate-400">
            Describe the cybercrime and/or attach a screenshot. The engine runs OCR,
            retrieves similar historical cases, and returns a structured triage with
            remediation steps cited to RBI, I4C, CERT-In and MITRE ATT&CK.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* ---- Input form ---- */}
          <form onSubmit={handleSubmit} className="glass rounded-2xl p-5 sm:p-6">
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-medium uppercase tracking-wider text-slate-400">
                Complaint narrative
              </label>
              <button
                type="button"
                onClick={() => setQuery(SAMPLE)}
                className="text-xs text-cyan-400 hover:text-cyan-300"
              >
                Insert sample
              </button>
            </div>
            <textarea
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              rows={7}
              placeholder="Describe what happened — who contacted the victim, what was requested, amounts, platforms involved…"
              className="glow-ring mb-5 w-full resize-y rounded-lg border border-white/10 bg-ink-900/60 px-3.5 py-3 text-sm leading-relaxed text-white placeholder:text-slate-500"
            />

            <label className="mb-2 block text-xs font-medium uppercase tracking-wider text-slate-400">
              Evidence screenshot
            </label>

            {!preview ? (
              <div
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                onClick={() => inputRef.current?.click()}
                className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 py-8 text-center transition ${
                  dragging
                    ? "border-cyan-400/70 bg-cyan-400/5"
                    : "border-white/15 hover:border-cyan-400/40 hover:bg-white/[0.03]"
                }`}
              >
                <svg
                  className="mb-2 h-8 w-8 text-slate-400"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.6"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <path d="M17 8l-5-5-5 5" />
                  <path d="M12 3v12" />
                </svg>
                <p className="text-sm text-slate-300">
                  <span className="text-cyan-400">Click to upload</span> or drag & drop
                </p>
                <p className="mt-1 text-xs text-slate-500">PNG, JPG or WEBP</p>
              </div>
            ) : (
              <div className="relative overflow-hidden rounded-xl border border-white/10">
                <img
                  src={preview}
                  alt="Evidence preview"
                  className="max-h-64 w-full object-contain bg-black/40"
                />
                <div className="flex items-center justify-between gap-3 border-t border-white/10 bg-ink-900/70 px-3 py-2">
                  <span className="truncate text-xs text-slate-300">{file?.name}</span>
                  <button
                    type="button"
                    onClick={clearFile}
                    className="shrink-0 rounded-md border border-white/10 px-2 py-1 text-xs text-slate-300 hover:border-rose-400/40 hover:text-rose-200"
                  >
                    Remove
                  </button>
                </div>
              </div>
            )}
            <input
              ref={inputRef}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(e) => acceptFile(e.target.files?.[0])}
            />

            {error && (
              <div className="mt-5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3.5 py-2.5 text-sm text-rose-200">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="glow-ring mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-violet-500 px-4 py-2.5 text-sm font-semibold text-ink-950 shadow-[0_0_24px_rgba(34,211,238,0.3)] transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {loading ? (
                <>
                  <Spinner /> Analyzing…
                </>
              ) : (
                <>Run Triage Analysis</>
              )}
            </button>
          </form>

          {/* ---- Result panel ---- */}
          {/* Bounded on desktop so the inner .thin-scroll actually scrolls.
              Without a max height the grid row just stretches to fit the report
              and the whole page grows, pushing the form out of view. */}
          <section className="glass flex min-h-[22rem] flex-col rounded-2xl p-5 sm:p-6 lg:sticky lg:top-24 lg:max-h-[calc(100vh-8rem)] lg:self-start">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-300">
                Triage Report
              </h3>
              {result && (
                <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2.5 py-1 text-xs text-cyan-300">
                  {result.retrieved_context_count} similar case
                  {result.retrieved_context_count === 1 ? "" : "s"} matched
                </span>
              )}
            </div>

            <div className="thin-scroll flex-1 overflow-y-auto">
              {loading && <LoadingState />}
              {!loading && !result && !error && <EmptyState />}
              {!loading && result && <StructuredReport result={result} />}
              {!loading && !result && error && (
                <div className="mt-6 rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                  {error}
                </div>
              )}
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}

function Spinner() {
  return (
    <span className="spin inline-block h-4 w-4 rounded-full border-2 border-ink-950/40 border-t-ink-950" />
  );
}

function EmptyState() {
  return (
    <div className="flex h-full flex-col items-center justify-center py-10 text-center">
      <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-slate-400">
        <svg
          className="h-6 w-6"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M16 13H8M16 17H8M10 9H8" />
        </svg>
      </div>
      <p className="text-sm text-slate-400">
        Your structured triage report will appear here.
      </p>
      <p className="mt-1 text-xs text-slate-500">
        Threat classification · legal category · mitigation steps
      </p>
    </div>
  );
}

function LoadingState() {
  return (
    <div className="space-y-3 py-2">
      <div className="flex items-center gap-2 text-sm text-cyan-300">
        <Spinner /> Retrieving cases and consulting the model…
      </div>
      {[...Array(5)].map((_, i) => (
        <div
          key={i}
          className="h-3 animate-pulse rounded bg-white/5"
          style={{ width: `${90 - i * 8}%` }}
        />
      ))}
    </div>
  );
}

const CONFIDENCE_STYLES = {
  high: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  medium: "border-amber-400/30 bg-amber-400/10 text-amber-300",
  low: "border-rose-400/30 bg-rose-400/10 text-rose-300",
  "n/a": "border-slate-400/30 bg-slate-400/10 text-slate-300",
};

const STEP_ACCENTS = {
  cyan: "border-cyan-400/30 bg-cyan-400/10 text-cyan-300",
  violet: "border-violet-400/30 bg-violet-400/10 text-violet-300",
};

// How a step was produced. Sourced steps get a citation the reader can open;
// model-written ones are marked so they are never mistaken for official guidance.
const ORIGIN_BADGES = {
  playbook: { label: "Sourced", style: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300" },
  mitre: { label: "MITRE ATT&CK", style: "border-sky-400/30 bg-sky-400/10 text-sky-300" },
  analyst: { label: "AI analyst", style: "border-slate-400/25 bg-slate-400/10 text-slate-400" },
};

/** Provenance line under a step: authority, instrument, and a link to it. */
function Citation({ step }) {
  const badge = ORIGIN_BADGES[step.origin] || ORIGIN_BADGES.analyst;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
      <span className={`rounded border px-1.5 py-0.5 font-medium ${badge.style}`}>
        {badge.label}
      </span>
      {step.reference_id && (
        <span className="font-mono text-slate-500">{step.reference_id}</span>
      )}
      {step.authority && <span className="text-slate-500">{step.authority}</span>}
      {step.url && (
        <a
          href={step.url}
          target="_blank"
          rel="noreferrer noopener"
          title={step.source || step.url}
          className="text-cyan-500 underline decoration-dotted underline-offset-2 hover:text-cyan-300"
        >
          source
        </a>
      )}
    </div>
  );
}

/** A titled, numbered list of steps with an accent color. */
function StepList({ title, steps, accent = "cyan" }) {
  const badge = STEP_ACCENTS[accent] || STEP_ACCENTS.cyan;
  return (
    <div>
      <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
        {title}
      </p>
      <ol className="space-y-3">
        {steps.map((step, i) => (
          <li key={step.reference_id || i} className="flex gap-3 text-sm leading-relaxed">
            <span
              className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold ${badge}`}
            >
              {i + 1}
            </span>
            <div className="min-w-0">
              <span className="text-slate-200">{step.text}</span>
              <Citation step={step} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

/** Renders the structured triage report from the agentic pipeline. */
function StructuredReport({ result }) {
  const {
    threat_classification,
    legal_category,
    consumer_mitigation_steps,
    soc_investigation_playbook,
    confidence,
    route_taken,
    reasoning,
    query,
    incident_tags,
  } = result || {};

  const consumerSteps = consumer_mitigation_steps || [];
  const socSteps = soc_investigation_playbook || [];

  const hasStructured =
    threat_classification || legal_category || consumerSteps.length || socSteps.length;

  if (!hasStructured) {
    return (
      <div className="mt-6 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
        The pipeline returned no triage content for this input. Try adding more
        detail about what happened.
      </div>
    );
  }

  const confKey = (confidence || "").toLowerCase();
  const confStyle = CONFIDENCE_STYLES[confKey] || CONFIDENCE_STYLES["n/a"];

  return (
    <div className="space-y-5">
      {/* Meta chips */}
      <div className="flex flex-wrap items-center gap-2">
        {confidence && (
          <span className={`rounded-full border px-2.5 py-1 text-xs font-medium ${confStyle}`}>
            confidence: {confidence}
          </span>
        )}
        {route_taken && (
          <span className="rounded-full border border-violet-400/30 bg-violet-400/10 px-2.5 py-1 text-xs text-violet-300">
            route: {route_taken}
          </span>
        )}
      </div>

      {/* Threat classification */}
      {threat_classification && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Threat Classification
          </p>
          <div className="inline-flex items-center gap-2 rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-3 py-2 text-sm font-semibold text-cyan-200">
            <span className="h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
            {threat_classification}
          </div>
        </div>
      )}

      {/* Legal category. Unlike the steps below this is model-generated and
          carries no citation, so it is marked as provisional — a small model
          will occasionally attach a real-sounding but wrong section number. */}
      {legal_category && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Legal / Regulatory Category
          </p>
          <p className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200">
            {legal_category}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px]">
            <span className={`rounded border px-1.5 py-0.5 font-medium ${ORIGIN_BADGES.analyst.style}`}>
              {ORIGIN_BADGES.analyst.label}
            </span>
            <span className="text-slate-500">
              Provisional classification — verify the section before citing it.
            </span>
          </div>
        </div>
      )}

      {/* Consumer mitigation — for the victim */}
      {consumerSteps.length > 0 && (
        <StepList
          title="For the Victim — Consumer Mitigation"
          steps={consumerSteps}
          accent="cyan"
        />
      )}

      {/* SOC investigation playbook — for the Indian cyber team */}
      {socSteps.length > 0 && (
        <StepList
          title="SOC Investigation Playbook — For the Cyber Team"
          steps={socSteps}
          accent="violet"
        />
      )}

      {/* Analyst reasoning */}
      {reasoning && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Analyst Reasoning
          </p>
          <p className="rounded-lg border border-white/10 bg-black/20 px-3 py-2.5 text-sm leading-relaxed text-slate-300">
            {reasoning}
          </p>
        </div>
      )}

      {/* What the pipeline actually read. With a screenshot attached this is the
          OCR dump after the sanitiser has removed the status-bar chrome, so it
          is the clearest evidence that step did its job. */}
      {query && (
        <div>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
            Analysed Incident · post-OCR
          </p>
          <p className="rounded-lg border border-white/10 bg-black/20 px-3 py-2.5 text-sm leading-relaxed text-slate-400">
            {query}
          </p>
          {incident_tags?.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {incident_tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded border border-white/10 bg-white/5 px-1.5 py-0.5 font-mono text-[11px] text-slate-400"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

