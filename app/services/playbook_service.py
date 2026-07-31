"""Trusted-source resolver for mitigation and investigation steps.

Actionable guidance in a triage report is not something an LLM should be
inventing, and it is not something that should fall back to a hardcoded blob of
generic advice. Every step this module returns comes from a corpus in
app/data/playbooks/ and carries the authority that published it plus a URL the
reader can open:

  india_consumer.json  victim-facing actions   (RBI, I4C/MHA, NPCI, CERT-In,
                                                DoT, SEBI)
  india_soc.json       analyst-facing actions  (RBI circulars, CERT-In s.70B
                                                Directions, CFCFRMS, BSA 2023)
  mitre_attack.json    supplementary TTP-level mitigations, generated from
                       MITRE's official STIX release by
                       scripts/refresh_playbooks.py

Selection is a deterministic tag match — no model call, so it cannot hallucinate
and it costs nothing. The model's own steps are still returned alongside these,
but they are labelled `analyst` rather than `playbook` so a reader can tell
sourced guidance from generated guidance.
"""

from __future__ import annotations

import json
import os
import re
from typing import Iterable

_PLAYBOOK_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "playbooks"
)

# ---------------------------------------------------------------------------
# Tag vocabulary. Maps incident wording -> the tags used across the corpora.
# Matched case-insensitively on word boundaries against the incident text and
# the model's threat classification.
# ---------------------------------------------------------------------------
_TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "upi": ("upi", "vpa", "gpay", "google pay", "phonepe", "paytm", "bhim",
            "qr code", "collect request", "rrn", "utr"),
    "otp": ("otp", "one time password", "one-time password", "verification code",
            "cvv", "mpin", "upi pin"),
    "kyc": ("kyc", "know your customer", "re-kyc", "aadhaar", "pan card",
            "account will be blocked", "update your details"),
    "card": ("debit card", "credit card", "card number", "atm", "pos ",
             "card was used", "cvv"),
    "netbanking": ("net banking", "netbanking", "internet banking", "neft",
                   "imps", "rtgs", "beneficiary"),
    "phishing": ("phishing", "fake link", "fake website", "smishing", "sms link",
                 "clicked a link", "spoofed", "fake sms", "fake email"),
    "impersonation": ("impersonat", "posing as", "pretending to be",
                      "bank official", "customer care", "fake police",
                      "claimed to be", "posed as"),
    "digital_arrest": ("digital arrest", "cbi", "enforcement directorate",
                       "narcotics", "money laundering case", "video call",
                       "arrest warrant", "custom department"),
    "remote_access": ("anydesk", "teamviewer", "quicksupport", "screen share",
                      "screen sharing", "remote access", "remote desktop",
                      "install an app", "accessibility permission"),
    "investment": ("investment", "trading", "stock tip", "crypto", "bitcoin",
                   "guaranteed return", "ponzi", "telegram group", "ipo alloc"),
    "job_scam": ("job offer", "work from home", "task based", "part time job",
                 "prepaid task", "registration fee", "youtube like"),
    "loan_app": ("loan app", "instant loan", "recovery agent", "morph",
                 "contact list", "harass", "nbfc"),
    "sim_swap": ("sim swap", "sim card stopped", "no network", "ported",
                 "duplicate sim", "imei"),
    "account_takeover": ("password changed", "logged in", "unauthorized access",
                         "unauthorised access", "account takeover",
                         "email changed", "mobile number changed",
                         "unauthorized transaction", "unauthorised transaction"),
    "social_media": ("facebook", "instagram", "whatsapp", "telegram", "twitter",
                     "profile hacked", "matrimonial", "dating"),
}

_MAX_CONSUMER_STEPS = 7
_MAX_SOC_STEPS = 6
_MAX_MITRE_STEPS = 2      # ATT&CK is supplementary context, not the backbone


def _load(filename: str) -> list[dict]:
    """Read one corpus file. A missing or malformed corpus is not fatal."""
    path = os.path.join(_PLAYBOOK_DIR, filename)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print(f"[playbook] corpus not found: {path}")
        return []
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[playbook] could not load {path}: {exc!r}")
        return []

    steps = data.get("steps") or []
    print(f"[playbook] loaded {len(steps):>3} steps from {filename}")
    return steps


_CONSUMER = _load("india_consumer.json")
_SOC = _load("india_soc.json")
_MITRE = _load("mitre_attack.json")

if not _CONSUMER or not _SOC:
    raise RuntimeError(
        "The India playbook corpora are missing or empty. Triage cannot emit "
        "sourced mitigation steps without them; check app/data/playbooks/."
    )


# Precompile one regex per tag so matching stays cheap on every request.
def _compile(keywords: Iterable[str]) -> re.Pattern:
    # Keywords are literal phrases; \b only helps where the edge is a word char.
    parts = []
    for kw in keywords:
        esc = re.escape(kw)
        left = r"\b" if kw[:1].isalnum() else ""
        right = r"\b" if kw[-1:].isalnum() else ""
        parts.append(f"{left}{esc}{right}")
    return re.compile("|".join(parts), re.IGNORECASE)


_TAG_PATTERNS = {tag: _compile(kws) for tag, kws in _TAG_KEYWORDS.items()}


def infer_tags(*texts: str) -> set[str]:
    """Derive incident tags from the cleaned incident text and classification."""
    blob = " ".join(t for t in texts if t)
    tags = {tag for tag, pat in _TAG_PATTERNS.items() if pat.search(blob)}
    tags.add("generic")  # baseline guidance always applies
    return tags


def _select(corpus: list[dict], tags: set[str], limit: int) -> list[dict]:
    """Pick the entries that apply to this incident.

    Entries flagged `always` are reserved a slot first. They are the actions
    whose value does not depend on the fraud type — calling 1930 inside the
    golden hour, filing on the NCRP, notifying the bank within three working
    days — and ranking them against incident-specific entries would let the two
    steps that most affect fund recovery fall off the end of the list.

    The remaining slots go to the entries sharing the most tags with the
    incident. An entry with no tag in common is dropped outright, so a card
    fraud case never pulls in SIM-swap guidance.

    The result is ordered by the corpus author's priority, which is the sequence
    a victim or analyst should actually work through.
    """
    anchors, scored = [], []
    for entry in corpus:
        entry_tags = set(entry.get("tags") or ())
        if not tags & entry_tags:
            continue
        if entry.get("always"):
            anchors.append(entry)
            continue
        # Incident-specific matches outrank the always-on `generic` entries.
        specificity = len(tags & (entry_tags - {"generic"}))
        scored.append((-specificity, entry.get("priority", 99), entry))

    scored.sort(key=lambda row: (row[0], row[1]))
    selected = anchors + [row[2] for row in scored[: max(limit - len(anchors), 0)]]
    selected.sort(key=lambda e: e.get("priority", 99))
    return selected


def _to_step(entry: dict) -> dict:
    """Shape a corpus entry into the API's step object."""
    return {
        "text": entry["text"],
        "source": entry.get("source"),
        "authority": entry.get("authority"),
        "url": entry.get("url"),
        "reference_id": entry.get("id"),
        "origin": "playbook",
    }


def consumer_steps(incident_text: str, threat_classification: str = "") -> list[dict]:
    """Victim-facing steps, sourced from the Indian regulatory corpus."""
    tags = infer_tags(incident_text, threat_classification)
    return [_to_step(e) for e in _select(_CONSUMER, tags, _MAX_CONSUMER_STEPS)]


def soc_steps(incident_text: str, threat_classification: str = "") -> list[dict]:
    """Analyst-facing steps: Indian statutory playbook first, ATT&CK after.

    The India corpus carries the legal and procedural obligations that actually
    bind an Indian cyber cell, so it leads. ATT&CK is appended as TTP-level
    context for attribution work.
    """
    tags = infer_tags(incident_text, threat_classification)
    steps = [_to_step(e) for e in _select(_SOC, tags, _MAX_SOC_STEPS)]

    for entry in _select(_MITRE, tags, _MAX_MITRE_STEPS):
        step = _to_step(entry)
        step["origin"] = "mitre"
        steps.append(step)

    return steps
