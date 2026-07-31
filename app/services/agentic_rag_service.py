"""
Agentic RAG pipeline for cybercrime / fraud triage — built on LangGraph.

Instead of a linear "retrieve -> stuff -> generate" chain, we run an explicit
state machine where cheap, fast LLM calls make routing/grading decisions and the
expensive generation step only runs when it is actually warranted. This buys us
three things a linear chain could not do:

  1. OCR sanitation      -> strips UI noise ("Sprint", battery %, clock) so the
                            carrier is never mistaken for part of the scam.
  2. Negative-constraint -> a grader drops retrieved cases that contradict the
     & temporal logic       user ("did NOT close the account", "money stolen
                            AFTER the freeze").
  3. Hallucination guard -> a critic rejects answers that cite UI-noise entities
                            or the wrong legal domain, and asks for one revision.
  4. Sourced remediation -> the model classifies but never prescribes. Every
                            actionable step is resolved from published Indian
                            regulatory playbooks and MITRE ATT&CK and carries a
                            citation, rather than being generated or filled in
                            from a generic canned blob.

STATE FLOW (how a request moves through the graph):

    START
      |
      v
    sanitize_context   (Node A)  raw_ocr_text + raw_query -> cleaned_context
      |
      v
    route_query        (Node B)  cleaned_context -> route
      |
      +---- route == "greeting" ----> greeting -----------------> END
      |
      +---- route == "retrieve" ----> retrieve  (Node C)
                                          |
                                          v
                                     grade_documents (Node D)  keep non-contradicting docs
                                          |
                                          v
                                     generate_triage (Node E)  structured TriageResult
                                          |            ^
                                          v            | one revision on failure
                                     critique       (Node F)
                                          |
                                          v
                                     ground_playbook (Node G)  attach sourced steps
                                          |
                                          v
                                         END

Every node receives the whole state dict and returns a *partial* dict of the
keys it wants to update; LangGraph merges those updates back into the state.
"""

import re
from typing import List, TypedDict

from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, START, END

from app.core.config import settings
from app.services.chroma_service import retrieve_similar_cases
from app.services import playbook_service


# ---------------------------------------------------------------------------
# 1. LLM handles — both are the same already-pulled model (settings.LLM_MODEL).
#    We keep TWO instances so we can tune temperature per job:
#      * fast_llm (temp 0)   -> deterministic routing / grading / critique.
#        These are short, structured, "environmentally friendly" calls.
#      * gen_llm  (temp 0.2) -> the single heavy generation step.
# ---------------------------------------------------------------------------
# `num_predict` caps output tokens per call. This is both a compute-saver and a
# safety net: small models occasionally loop and emit the same text forever, so
# we bound generation instead of letting a request hang for minutes.
fast_llm = ChatOllama(model=settings.LLM_MODEL, temperature=0, num_predict=256)
# 384 is ample now that generation produces four short fields rather than two
# lists of remediation steps.
gen_llm = ChatOllama(model=settings.LLM_MODEL, temperature=0.2, num_predict=384)


# ---------------------------------------------------------------------------
# 2. Structured output schemas. Each fast node is bound to one of these via
#    `.with_structured_output(Model)`, which forces the LLM to return JSON that
#    validates against the schema — no brittle string parsing.
# ---------------------------------------------------------------------------
class RouterDecision(BaseModel):
    """Node B output — is this an actual incident that needs case retrieval?"""
    is_threat: bool = Field(
        description="True if the message describes a cybercrime, fraud, scam, or "
        "financial-security incident that needs analysis. False for greetings, "
        "small talk, or empty/irrelevant messages."
    )
    reason: str = Field(description="One short sentence explaining the decision.")


class GradeDecision(BaseModel):
    """Node D output — which retrieved documents survive the relevance/logic check."""
    kept_indices: List[int] = Field(
        default_factory=list,
        description="Zero-based indices of the documents that are RELEVANT and do "
        "NOT contradict the user's negative constraints or timeline. Return an "
        "empty list if none are usable.",
    )
    reason: str = Field(description="Brief justification for what was kept or dropped.")


class TriageResult(BaseModel):
    """Node E output — the model's assessment of the incident.

    Deliberately contains NO remediation steps. Asking the model for them and
    then merging its output against the playbooks was tried and measured: on a
    live run roughly four in five generated steps were paraphrases of the
    sourced guidance the model had just been shown, and no lexical similarity
    threshold separated the paraphrases from the genuinely additive ones
    reliably. Classification and grounding are what the model is actually good
    at; the actions come from Node G, where every one of them has a citation.
    """
    threat_classification: str = Field(
        description="Concise threat type, e.g. 'Phishing / KYC OTP fraud', "
        "'Unauthorized UPI debit', 'Investment scam'."
    )
    legal_category: str = Field(
        description="Relevant category under the INDIAN framework (e.g. "
        "unauthorized electronic transaction under RBI guidelines, IT Act 2000 "
        "offence type). Do NOT cite US statutes or agencies."
    )
    confidence: str = Field(
        description="One of 'high', 'medium', or 'low' based on how well the "
        "historical context supports the analysis."
    )
    reasoning: str = Field(
        description="Short explanation grounding the classification in the context."
    )


class CriticVerdict(BaseModel):
    """Node F output — does the generated triage pass the hallucination checks?"""
    grounded: bool = Field(
        description="True only if the answer is well-grounded and passes ALL checks below."
    )
    mentions_ui_noise: bool = Field(
        description="True if the answer tells the user to contact / blame a phone "
        "carrier, device, app-store, or other UI-chrome entity (e.g. 'Sprint')."
    )
    wrong_legal_domain: bool = Field(
        description="True if the answer cites criminal law / unrelated statutes "
        "instead of consumer-banking / financial-fraud regulations."
    )
    mentions_us_jurisdiction: bool = Field(
        description="True if the answer names ANY US agency or statute — e.g. FBI, "
        "FTC, CFPB, IC3, SEC, EFTA, '18 U.S.C.', or tells the victim to report to a "
        "US body. The output must be India-only."
    )
    issues: str = Field(description="What to fix, if anything (used for the revision).")


# ---------------------------------------------------------------------------
# 3. Graph state. This TypedDict is the single object passed between every node.
#    Nodes read from it and return partial updates that get merged back in.
# ---------------------------------------------------------------------------
class TriageState(TypedDict, total=False):
    raw_query: str            # the citizen's typed complaint (may be empty)
    raw_ocr_text: str         # raw EasyOCR dump from the screenshot (may be empty, noisy)
    cleaned_context: str      # Node A output: fused, de-noised incident description
    retrieved_docs: List[str] # Node C fills; Node D overwrites with the kept subset
    generation_output: dict   # Node E/G/greeting output: the triage report as a dict
    revision_count: int       # how many times Node F has bounced back to Node E
    route: str                # "greeting" | "retrieve" — drives the conditional edge
    critic_feedback: str      # Node F notes fed back into Node E on a revision
    incident_tags: List[str]  # Node G: tags used to resolve the trusted playbooks


# ===========================================================================
# NODE A — OCR SANITIZER
# Fuses the raw OCR text with the typed query and strips visual UI noise so the
# downstream nodes reason about the ACTUAL incident, not the phone's status bar.
# ===========================================================================
_sanitize_prompt = ChatPromptTemplate.from_template(
    """You are a forensic pre-processor for a cybercrime triage system.

You receive (a) a citizen's typed complaint and (b) raw OCR text scraped from a
screenshot. The OCR text is polluted with phone/app UI noise that is IRRELEVANT
to the crime, such as: cellular carrier names (e.g. "Sprint", "Verizon"), the
clock/time, battery percentage, signal bars, Wi-Fi icons, status-bar labels,
and navigation buttons.

Produce ONE clean paragraph describing ONLY the actual incident: who contacted
the victim, what was requested, amounts, platforms/banks, account actions, and
the TIMELINE of events. Preserve negations exactly (e.g. "did NOT close the
account") and the order of events.

Rules:
- REMOVE all carrier names, timestamps, battery %, and status-bar noise.
- Do NOT invent facts. If a field is unknown, omit it.
- If the typed complaint and OCR conflict, keep both signals but describe them.

TYPED COMPLAINT:
{raw_query}

RAW OCR TEXT:
{raw_ocr_text}

CLEANED INCIDENT DESCRIPTION:"""
)


# Instruction-tuned models like to announce what they are about to produce.
# That preamble is not part of the incident, and it goes on to pollute the
# retrieval query, the generator prompt and the report the citizen reads.
_PREAMBLE = re.compile(
    r"^\s*(here(?:'s| is)|below is|the following is|this is|cleaned)\b[^:\n]{0,100}:\s*",
    re.IGNORECASE,
)


def _strip_preamble(text: str) -> str:
    """Drop a leading 'Here is the cleaned incident description:' style lead-in."""
    stripped = _PREAMBLE.sub("", text, count=1).strip()
    # Only accept the strip if something substantive survives it.
    return stripped if len(stripped) >= 40 else text.strip()


def sanitize_context(state: TriageState) -> TriageState:
    """Node A: raw_query + raw_ocr_text  ->  cleaned_context (string)."""
    raw_query = (state.get("raw_query") or "").strip()
    raw_ocr = (state.get("raw_ocr_text") or "").strip()

    # If there is no OCR noise to clean, skip the LLM call entirely (compute saver).
    if not raw_ocr:
        return {"cleaned_context": raw_query}

    chain = _sanitize_prompt | fast_llm | StrOutputParser()
    try:
        cleaned = _strip_preamble(
            chain.invoke({"raw_query": raw_query, "raw_ocr_text": raw_ocr})
        )
    except Exception:
        # Fail safe: fall back to a naive fusion so the pipeline never dies here.
        cleaned = f"{raw_query}\n{raw_ocr}".strip()

    return {"cleaned_context": cleaned or raw_query}


# ===========================================================================
# NODE B — ROUTER (compute saver)
# A single fast, structured call decides whether we even need the RAG machinery.
# Greetings / small talk short-circuit straight to a canned reply.
# ===========================================================================
_router_prompt = ChatPromptTemplate.from_template(
    """Classify the following message for a cybercrime triage system.

Decide if it describes a real cybercrime / fraud / financial-security incident
that requires retrieving similar historical cases, OR if it is just a greeting,
small talk, or an empty/irrelevant message.

MESSAGE:
{cleaned_context}"""
)


def route_query(state: TriageState) -> TriageState:
    """Node B: cleaned_context -> route."""
    context = (state.get("cleaned_context") or "").strip()

    # Empty input is trivially a non-threat -> greeting path.
    if not context:
        return {"route": "greeting"}

    router = fast_llm.with_structured_output(RouterDecision)
    try:
        decision: RouterDecision = router.invoke(_router_prompt.format(cleaned_context=context))
        is_threat = bool(decision.is_threat)
    except Exception:
        # If the router fails, err on the side of doing the full analysis.
        is_threat = True

    return {"route": "retrieve" if is_threat else "greeting"}


# ===========================================================================
# NODE C — RETRIEVER
# Thin wrapper over the EXISTING chroma_service. We do not ingest/embed anything
# here; we only query the pre-built 300k-complaint vector store.
# ===========================================================================
def retrieve(state: TriageState) -> TriageState:
    """Node C: cleaned_context -> retrieved_docs (list of page_content strings)."""
    context = state.get("cleaned_context") or ""
    try:
        docs = retrieve_similar_cases(context, top_k=4)
        contents = [d.page_content for d in docs]
    except Exception as exc:
        # Don't hide retrieval failures as "no matches" — the graph degrades
        # gracefully, but the cause needs to be visible in the logs.
        print(f"[agentic_rag] retrieval failed: {exc!r}")
        contents = []
    return {"retrieved_docs": contents}


# ===========================================================================
# NODE D — DOCUMENT GRADER (relevance + negative/temporal logic)
# Looks at ALL retrieved docs in one cheap call and keeps only the ones that are
# relevant AND do not contradict the user's negations or timeline.
# ===========================================================================
_grader_prompt = ChatPromptTemplate.from_template(
    """You are grading retrieved historical complaints for relevance to a NEW incident.

Keep a document ONLY if it is topically relevant AND does not contradict the
user's stated facts. In particular, DROP a document if:
- it asserts something the user explicitly negated
  (user: "the bank did NOT close my account" -> drop "account was closed" cases), or
- it conflicts with the user's timeline of events, or
- it is about an unrelated topic.

NEW INCIDENT:
{cleaned_context}

RETRIEVED DOCUMENTS (indexed):
{documents}

Return the zero-based indices of the documents to KEEP."""
)


def grade_documents(state: TriageState) -> TriageState:
    """Node D: retrieved_docs -> retrieved_docs (filtered to the kept subset)."""
    docs = state.get("retrieved_docs") or []
    if not docs:
        return {"retrieved_docs": []}

    # Number the docs so the model can refer to them by index.
    numbered = "\n\n".join(f"[{i}] {d}" for i, d in enumerate(docs))
    grader = fast_llm.with_structured_output(GradeDecision)
    try:
        decision: GradeDecision = grader.invoke(
            _grader_prompt.format(cleaned_context=state.get("cleaned_context", ""), documents=numbered)
        )
        kept = [docs[i] for i in decision.kept_indices if 0 <= i < len(docs)]
    except Exception:
        # If grading fails, keep everything rather than lose all context.
        kept = docs

    return {"retrieved_docs": kept}


# ===========================================================================
# NODE E — TRIAGE ANALYST (the single heavy generation step)
# Produces the structured TriageResult grounded ONLY in the graded docs. If the
# grader kept nothing, we run a clearly-labelled LOW-CONFIDENCE fallback instead
# of hallucinating a match. On a revision pass, the critic's feedback is injected.
# ===========================================================================
# The strict jurisdiction-override system prompt. The retrieved context is
# US-based (CFPB), so the model must use it ONLY for scam mechanics and must
# frame its conclusions under the Indian framework.
_GENERATOR_SYSTEM_PROMPT = """You are an elite Cybercrime Analyst for an Indian Security Operations Center. You will be provided with a user's cybercrime incident and historical fraud context.

CRITICAL INSTRUCTION ON JURISDICTION:
The retrieved historical context comes from a US-based database. You will use this context ONLY to analyze the mechanics, behaviors, and tactics of the scam. You MUST COMPLETELY IGNORE all US-based legal statutes and agencies (e.g., FTC, EFTA, 18 U.S.C., CFPB) present in the retrieved context.

Your job is CLASSIFICATION, not remediation. Do NOT write mitigation steps, advice, or an action plan — those are resolved separately from published Indian regulatory playbooks. Produce exactly four fields:

1. threat_classification: the specific fraud type and delivery method, e.g. "Phishing / KYC OTP fraud (vishing)", "Unauthorised UPI debit via collect request", "Task-based job scam". Be specific — "Financial Fraud" is too vague to be useful.
2. legal_category: the specific Indian regulatory or statutory framing, e.g. "Unauthorised electronic banking transaction under RBI circular DBR.No.Leg.BC.78/09.07.005/2017-18", "Cheating by personation under the IT Act 2000 s.66D". Never cite US law.
3. confidence: 'high', 'medium' or 'low', based on how well the retrieved context supports the classification.
4. reasoning: two or three sentences grounding the classification in the incident and the retrieved context.

Additional rules:
- NEVER attribute the fraud to a phone carrier, device maker, or app store (e.g. "Sprint") — those are UI artifacts in the screenshot, not the fraudster.
- Respect the incident's negations and event timeline."""

_generate_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", _GENERATOR_SYSTEM_PROMPT),
        (
            "human",
            "{revision_note}\n\nHISTORICAL CONTEXT (US-sourced — use for tactics only):\n"
            "{context}\n\nINCIDENT:\n{cleaned_context}",
        ),
    ]
)

_FALLBACK_CONTEXT = (
    "NO reliable historical cases matched this incident. Analyze from first "
    "principles and set confidence to 'low'."
)

_VALID_CONFIDENCE = {"high", "medium", "low", "n/a"}


# Deterministic jurisdiction guard. The remediation steps are India-only by
# construction now (they come from the Indian corpora), but the model still
# writes legal_category and reasoning freely, and the retrieved context is full
# of US agencies for it to copy. A regex hit here forces a revision even when
# the LLM critic was satisfied. (Word-boundary matched to avoid false positives:
# `\bSEC\b` will not fire on "section", and SEBI is unaffected.)
_US_JURISDICTION = re.compile(
    r"\b(FTC|FBI|CFPB|IC3|SEC|EFTA|FDIC|OCC|FinCEN|"
    r"Federal Trade Commission|Federal Bureau|Consumer Financial Protection|"
    r"U\.?S\.?C\.?|United States|Attorney General)\b",
    re.IGNORECASE,
)


def _mentions_us_jurisdiction(output: dict) -> bool:
    """Does the model's free text name a US agency or statute?"""
    return any(
        _US_JURISDICTION.search(output.get(field) or "")
        for field in ("threat_classification", "legal_category", "reasoning")
    )


def _clean_output(output: dict) -> dict:
    """Tidy the model's structured output (small LLMs leak whitespace / junk)."""
    for field in ("threat_classification", "legal_category", "reasoning"):
        output[field] = (output.get(field) or "").strip()

    conf = (output.get("confidence") or "").strip().lower()
    output["confidence"] = conf if conf in _VALID_CONFIDENCE else "low"
    return output


def generate_triage(state: TriageState) -> TriageState:
    """Node E: cleaned_context (+ graded docs) -> generation_output (dict)."""
    docs = state.get("retrieved_docs") or []

    # Fallback path: no docs survived grading -> label it low-confidence.
    context = "\n\n".join(docs) if docs else _FALLBACK_CONTEXT

    # On a revision, feed the critic's complaint back into the prompt.
    feedback = state.get("critic_feedback") or ""
    revision_note = f"- Fix these issues from the previous attempt: {feedback}" if feedback else ""

    generator = gen_llm.with_structured_output(TriageResult)
    try:
        result: TriageResult = generator.invoke(
            _generate_prompt.format(
                context=context,
                cleaned_context=state.get("cleaned_context", ""),
                revision_note=revision_note,
            )
        )
        output = _clean_output(result.model_dump())
        # Force low confidence on the fallback path regardless of model optimism.
        if not docs:
            output["confidence"] = "low"
    except Exception as e:
        # No canned advice here. Classification degrades to "undetermined", and
        # Node G still attaches the sourced playbook steps, so the victim is
        # never left without actionable guidance.
        print(f"[agentic_rag] generation failed: {e!r}")
        output = {
            "threat_classification": "Undetermined",
            "legal_category": "Undetermined (apply Indian framework)",
            "confidence": "low",
            "reasoning": (
                "Automated classification could not be completed; the steps below "
                "are the baseline actions published by the Indian authorities."
            ),
        }

    return {"generation_output": output}


# ===========================================================================
# NODE F — HALLUCINATION CRITIC
# Inspects Node E's output and bounces it back ONCE if it cites UI-noise entities
# or the wrong legal domain. This is the anti-"Sprint" safety net.
# ===========================================================================
_critic_prompt = ChatPromptTemplate.from_template(
    """You are a strict reviewer of an INDIAN cybercrime triage report.

Fail the report (grounded = false) if ANY of these are true:
- It names ANY US agency or statute (FBI, FTC, CFPB, IC3, SEC, EFTA, "18 U.S.C.")
  or tells the victim to report to a US body. The report must be India-only and
  should use Indian resources (1930 helpline, cybercrime.gov.in, RBI, I4C).
- It tells the victim to contact/blame a phone carrier, device, or app store
  (e.g. "Sprint", "Verizon", "Apple") — those are UI noise, not the criminal.
- It cites unrelated criminal law instead of the Indian consumer-banking /
  financial-fraud framework.
- It contradicts the incident's negations or timeline.

INCIDENT:
{cleaned_context}

REPORT UNDER REVIEW:
{generation_output}"""
)


def critique(state: TriageState) -> TriageState:
    """Node F: generation_output -> critic_feedback + revision_count (if failing)."""
    output = state.get("generation_output") or {}
    critic = fast_llm.with_structured_output(CriticVerdict)
    try:
        verdict: CriticVerdict = critic.invoke(
            _critic_prompt.format(
                cleaned_context=state.get("cleaned_context", ""),
                generation_output=output,
            )
        )
        failed = (
            (not verdict.grounded)
            or verdict.mentions_ui_noise
            or verdict.wrong_legal_domain
            or verdict.mentions_us_jurisdiction
        )
        feedback = verdict.issues if failed else ""
    except Exception:
        # If the critic itself errors, accept the report (avoid infinite risk).
        failed = False
        feedback = ""

    # The regex is not a second opinion — it overrules a passing verdict. A small
    # critic model regularly waves through a report that names the FTC outright.
    if _mentions_us_jurisdiction(output):
        failed = True
        feedback = (
            "The report names a US agency or statute. Reclassify using only the "
            "Indian framework (RBI circulars, IT Act 2000, BNS). " + feedback
        ).strip()

    if failed:
        # Signal a revision; the conditional edge decides whether we still have budget.
        return {
            "critic_feedback": feedback,
            "revision_count": state.get("revision_count", 0) + 1,
        }
    # Passed — clear any stale feedback.
    return {"critic_feedback": ""}


# ===========================================================================
# NODE G — PLAYBOOK GROUNDING
# Resolves the actionable steps from the trusted corpora (Indian regulators +
# MITRE ATT&CK). Every actionable step in a triage report originates here, and
# therefore every one of them carries an authority and a citation.
#
# This node is why there is no canned-default block anywhere in this file: a
# legitimate complaint always gets real, attributable guidance.
# ===========================================================================


def ground_playbook(state: TriageState) -> TriageState:
    """Node G: generation_output -> generation_output with sourced steps attached.

    Both tracks are resolved wholly from the trusted corpora. Tags are derived
    from the incident text as well as the classification, so the right guidance
    still surfaces when the model's classification comes back vague — a live run
    that produced only "Financial Fraud" still resolved kyc/otp/upi correctly off
    the narrative.
    """
    output = dict(state.get("generation_output") or {})
    incident = state.get("cleaned_context", "")
    classification = output.get("threat_classification") or ""

    output["consumer_mitigation_steps"] = playbook_service.consumer_steps(
        incident, classification
    )
    output["soc_investigation_playbook"] = playbook_service.soc_steps(
        incident, classification
    )

    return {
        "generation_output": output,
        "incident_tags": sorted(playbook_service.infer_tags(incident, classification)),
    }


# ===========================================================================
# GREETING — non-LLM canned reply for the "not a threat" route.
# This one stays: it is not triage output, it is a prompt for more information.
# ===========================================================================
def greeting(state: TriageState) -> TriageState:
    """Terminal node for greetings/small talk — no retrieval, no heavy generation."""
    return {
        "generation_output": {
            "threat_classification": "No threat detected",
            "legal_category": "N/A",
            "consumer_mitigation_steps": [
                {
                    "text": "Describe the incident (what happened, amounts, who "
                    "contacted you) and attach any screenshots so I can triage it.",
                    "origin": "analyst",
                }
            ],
            "soc_investigation_playbook": [],
            "confidence": "n/a",
            "reasoning": "The message appears to be a greeting or general chat rather "
            "than a cybercrime report.",
        },
        "incident_tags": [],
    }


# ===========================================================================
# CONDITIONAL EDGE FUNCTIONS
# These pure functions read the state and return the NAME of the next node.
# ===========================================================================
def _route_after_router(state: TriageState) -> str:
    """After Node B: greeting path vs full retrieval path."""
    return "greeting" if state.get("route") == "greeting" else "retrieve"


def _route_after_critic(state: TriageState) -> str:
    """After Node F: revise once (back to Node E) or move on to grounding.

    We revise only if the critic left feedback AND we still have budget
    (revision_count <= 1 means at most one bounce-back).
    """
    if state.get("critic_feedback") and state.get("revision_count", 0) <= 1:
        return "generate_triage"
    return "ground_playbook"


# ===========================================================================
# 4. BUILD & COMPILE THE GRAPH (done once at import time).
# ===========================================================================
def _build_graph():
    workflow = StateGraph(TriageState)

    # Register nodes.
    workflow.add_node("sanitize_context", sanitize_context)   # A
    workflow.add_node("route_query", route_query)             # B
    workflow.add_node("retrieve", retrieve)                   # C
    workflow.add_node("grade_documents", grade_documents)     # D
    workflow.add_node("generate_triage", generate_triage)     # E
    workflow.add_node("critique", critique)                   # F
    workflow.add_node("ground_playbook", ground_playbook)     # G
    workflow.add_node("greeting", greeting)                   # greeting terminal

    # Linear entry: START -> A -> B.
    workflow.add_edge(START, "sanitize_context")
    workflow.add_edge("sanitize_context", "route_query")

    # B branches: greeting (skip RAG) or retrieve.
    workflow.add_conditional_edges(
        "route_query",
        _route_after_router,
        {"greeting": "greeting", "retrieve": "retrieve"},
    )

    # RAG path: C -> D -> E -> F.
    workflow.add_edge("retrieve", "grade_documents")
    workflow.add_edge("grade_documents", "generate_triage")
    workflow.add_edge("generate_triage", "critique")

    # F branches: one revision back to E, or on to grounding.
    workflow.add_conditional_edges(
        "critique",
        _route_after_critic,
        {"generate_triage": "generate_triage", "ground_playbook": "ground_playbook"},
    )

    # G is the last stop on the RAG path.
    workflow.add_edge("ground_playbook", END)

    # Greeting is terminal.
    workflow.add_edge("greeting", END)

    return workflow.compile()


# The compiled graph — reused across requests.
graph = _build_graph()


# ===========================================================================
# 5. PUBLIC ENTRYPOINT for the FastAPI router.
# Async so it fits the async endpoint; ChatOllama supports async execution and
# LangGraph runs the sync nodes without blocking the event loop.
# ===========================================================================
async def run_agentic_triage(raw_query: str, raw_ocr_text: str = "") -> dict:
    """Run the full agentic pipeline and return the final graph state (a dict)."""
    final_state = await graph.ainvoke(
        {
            "raw_query": raw_query or "",
            "raw_ocr_text": raw_ocr_text or "",
            "cleaned_context": "",
            "retrieved_docs": [],
            "generation_output": {},
            "revision_count": 0,
            "route": "",
            "critic_feedback": "",
            "incident_tags": [],
        }
    )
    return final_state
