import { API_BASE_URL } from "../lib/config";

/**
 * Submit an incident to the backend agentic RAG pipeline.
 *
 * Mirrors POST /api/v1/analyze, which accepts a multipart form with an optional
 * `query` text field and an optional `file` image.
 *
 * Each entry in the two step arrays is an object, not a string:
 *   { text, origin: "playbook"|"mitre"|"analyst", authority, source, url, reference_id }
 * `origin` is what lets the UI separate sourced guidance from model-written
 * guidance — do not flatten these to plain strings.
 *
 * @param {{ query?: string, file?: File | null }} payload
 * @returns {Promise<{
 *   query: string,
 *   retrieved_context_count: number,
 *   threat_classification: string | null,
 *   legal_category: string | null,
 *   consumer_mitigation_steps: Array<object>,
 *   soc_investigation_playbook: Array<object>,
 *   confidence: string | null,
 *   route_taken: string | null,
 *   reasoning: string | null,
 *   incident_tags: string[],
 * }>}
 */
export async function analyzeIncident({ query, file }) {
  const form = new FormData();
  if (query && query.trim()) form.append("query", query.trim());
  if (file) form.append("file", file);

  let res;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/analyze`, {
      method: "POST",
      body: form,
    });
  } catch {
    throw new Error(
      `Could not reach the backend at ${API_BASE_URL}. Is the FastAPI server running?`
    );
  }

  let data = null;
  try {
    data = await res.json();
  } catch {
    // Non-JSON error body (e.g. proxy/HTML error page)
  }

  if (!res.ok) {
    const detail =
      (data && (data.detail || data.message)) ||
      `Request failed with status ${res.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  return data;
}
