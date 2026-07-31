from typing import List, Optional

from pydantic import BaseModel


class TriageStep(BaseModel):
    """One actionable step, carrying where it came from.

    Provenance is part of the contract: a reader must be able to tell guidance
    that was resolved from a published playbook from guidance the model wrote.
    """
    text: str
    origin: str = "analyst"                     # "playbook" | "mitre" | "analyst"
    authority: Optional[str] = None             # e.g. "Reserve Bank of India"
    source: Optional[str] = None                # circular / direction / technique
    url: Optional[str] = None                   # citation the reader can open
    reference_id: Optional[str] = None          # e.g. "IN-CONS-003", "M1032"


class AnalysisResponse(BaseModel):
    query: str                                  # the sanitized incident description
    retrieved_context_count: int                # docs that survived the grader

    # --- Structured fields produced by the agentic pipeline ---
    threat_classification: Optional[str] = None
    legal_category: Optional[str] = None
    # Dual-track, India-localized solutions:
    consumer_mitigation_steps: List[TriageStep] = []   # for the victim
    soc_investigation_playbook: List[TriageStep] = []  # for the Indian SOC/cyber team
    confidence: Optional[str] = None            # "high" | "medium" | "low" | "n/a"
    route_taken: Optional[str] = None           # "greeting" | "retrieve"
    reasoning: Optional[str] = None             # analyst's grounding explanation
    incident_tags: List[str] = []               # tags used to resolve the playbooks
