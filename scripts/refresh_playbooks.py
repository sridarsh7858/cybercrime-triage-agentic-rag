"""Refresh the MITRE ATT&CK slice of the trusted playbook corpus.

Downloads MITRE's official Enterprise ATT&CK STIX bundle, keeps only the
techniques that actually occur in consumer financial fraud and social
engineering, resolves each one to the mitigations MITRE publishes against it,
and writes a compact corpus to app/data/playbooks/mitre_attack.json.

The mitigation text written out is MITRE's own prose — this script never
paraphrases or invents guidance, it only selects and reshapes.

Run it offline, ahead of time:

    python scripts/refresh_playbooks.py

The API is public and needs no key. The full bundle is ~50 MB; only the
filtered result (a few hundred KB) is kept on disk, so the running service
never touches the network.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from datetime import date

ATTACK_STIX_URL = (
    "https://raw.githubusercontent.com/mitre-attack/attack-stix-data/"
    "master/enterprise-attack/enterprise-attack.json"
)

OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "app", "data", "playbooks", "mitre_attack.json",
)

# ATT&CK techniques that genuinely show up in UPI / OTP / KYC / impersonation
# fraud, mapped onto this project's incident tag vocabulary. Pinning technique
# IDs (rather than keyword-matching names) keeps the selection stable across
# ATT&CK releases, which rename techniques fairly often.
TECHNIQUE_TAGS: dict[str, list[str]] = {
    "T1566": ["phishing"],                       # Phishing
    "T1566.001": ["phishing"],                   # Spearphishing Attachment
    "T1566.002": ["phishing"],                   # Spearphishing Link
    "T1566.003": ["phishing", "social_media"],   # Spearphishing via Service
    "T1566.004": ["phishing", "impersonation"],  # Spearphishing Voice
    "T1598": ["phishing", "kyc"],                # Phishing for Information
    "T1598.004": ["impersonation", "otp"],       # Spearphishing Voice
    "T1656": ["impersonation", "digital_arrest"],# Impersonation
    "T1621": ["otp", "account_takeover"],        # MFA Request Generation
    "T1111": ["otp", "sim_swap"],                # MFA Interception
    "T1078": ["account_takeover"],               # Valid Accounts
    "T1098": ["account_takeover"],               # Account Manipulation
    "T1098.005": ["account_takeover", "otp"],    # Device Registration
    "T1219": ["remote_access"],                  # Remote Access Software/Tools
    "T1657": ["generic"],                        # Financial Theft
    "T1585": ["investment", "job_scam"],         # Establish Accounts
    "T1585.001": ["social_media", "investment"], # Social Media Accounts
    "T1586": ["account_takeover"],               # Compromise Accounts
    "T1583.001": ["phishing", "loan_app"],       # Acquire Infrastructure: Domains
    "T1036": ["impersonation", "loan_app"],      # Masquerading
    "T1204.002": ["remote_access", "loan_app"],  # User Execution: Malicious File
    "T1539": ["account_takeover"],               # Steal Web Session Cookie
    "T1550": ["account_takeover"],               # Use Alternate Authentication Material
}

# ATT&CK mitigations aimed squarely at corporate intrusion defence. They are
# real MITRE guidance but meaningless for a UPI/OTP fraud case, and leaving them
# in is how a triage report ends up telling a cyber cell to tune group policy.
EXCLUDED_MITIGATIONS = {
    "M1013",  # Application Developer Guidance
    "M1015",  # Active Directory Configuration
    "M1022",  # Restrict File and Directory Permissions
    "M1026",  # Privileged Account Management
    "M1028",  # Operating System Configuration
    "M1030",  # Network Segmentation
    "M1034",  # Limit Hardware Installation
    "M1037",  # Filter Network Traffic
}

_WHITESPACE = re.compile(r"\s+")
# ATT&CK prose is Markdown and cites other objects as [Name](url) / (Citation: X).
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_CITATION = re.compile(r"\(Citation:[^)]*\)")


def _attack_id(obj: dict) -> str | None:
    """Pull the human-facing ATT&CK ID (T1566, M1017) out of a STIX object."""
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("external_id")
    return None


def _attack_url(obj: dict) -> str | None:
    for ref in obj.get("external_references", []):
        if ref.get("source_name") == "mitre-attack":
            return ref.get("url")
    return None


def _first_sentences(text: str, limit: int = 2) -> str:
    """Condense a MITRE description to its opening sentences.

    Mitigation descriptions run several paragraphs; a triage report needs the
    actionable opening, not the full essay.
    """
    text = _CITATION.sub("", text or "")
    text = _MD_LINK.sub(r"\1", text)
    text = _WHITESPACE.sub(" ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:limit]).strip()


def _is_live(obj: dict) -> bool:
    return not obj.get("revoked") and not obj.get("x_mitre_deprecated")


def main() -> int:
    print(f"[refresh] downloading {ATTACK_STIX_URL}")
    with urllib.request.urlopen(ATTACK_STIX_URL, timeout=300) as resp:
        bundle = json.load(resp)
    objects = bundle.get("objects", [])
    print(f"[refresh] parsed {len(objects)} STIX objects")

    # Index the three object kinds we need, keyed by STIX id.
    techniques: dict[str, dict] = {}
    mitigations: dict[str, dict] = {}
    mitigates: list[tuple[str, str]] = []  # (mitigation stix id, technique stix id)

    for obj in objects:
        otype = obj.get("type")
        if otype == "attack-pattern" and _is_live(obj):
            techniques[obj["id"]] = obj
        elif otype == "course-of-action" and _is_live(obj):
            mitigations[obj["id"]] = obj
        elif otype == "relationship" and obj.get("relationship_type") == "mitigates":
            mitigates.append((obj.get("source_ref", ""), obj.get("target_ref", "")))

    # Resolve our pinned technique IDs to their STIX ids.
    wanted: dict[str, dict] = {}  # stix id -> technique object
    for stix_id, tech in techniques.items():
        tid = _attack_id(tech)
        if tid in TECHNIQUE_TAGS:
            wanted[stix_id] = tech

    # Not fatal: ATT&CK revokes and re-parents techniques between releases, and
    # some India-specific scam patterns (e.g. 'digital arrest') have no ATT&CK
    # analogue at all. The India corpora remain the authority for those.
    missing = set(TECHNIQUE_TAGS) - {_attack_id(t) for t in wanted.values()}
    if missing:
        print(f"[refresh] note: not present in this ATT&CK release: {sorted(missing)}")

    # Collapse (mitigation, technique) pairs into one entry per mitigation,
    # carrying the union of tags and the techniques it covers.
    entries: dict[str, dict] = {}
    for mit_ref, tech_ref in mitigates:
        tech = wanted.get(tech_ref)
        mit = mitigations.get(mit_ref)
        if not tech or not mit:
            continue
        mid, tid = _attack_id(mit), _attack_id(tech)
        if not mid or not tid or mid in EXCLUDED_MITIGATIONS:
            continue

        entry = entries.setdefault(
            mid,
            {
                "id": mid,
                "text": _first_sentences(mit.get("description", "")),
                "authority": "MITRE",
                "source": "",
                "url": _attack_url(mit),
                "tags": set(),
                "techniques": [],
                "priority": 50,
            },
        )
        entry["tags"].update(TECHNIQUE_TAGS[tid])
        entry["techniques"].append(f"{tid} {tech.get('name', '')}".strip())

    out_steps = []
    for entry in entries.values():
        techs = sorted(set(entry["techniques"]))
        entry["techniques"] = techs
        entry["tags"] = sorted(entry["tags"])
        entry["source"] = (
            f"MITRE ATT&CK Enterprise mitigation {entry['id']} — mitigates "
            + "; ".join(techs[:3])
            + ("; …" if len(techs) > 3 else "")
        )
        if entry["text"]:
            out_steps.append(entry)

    out_steps.sort(key=lambda e: e["id"])

    payload = {
        "playbook": "MITRE ATT&CK (Enterprise) — fraud & social-engineering slice",
        "revision": bundle.get("x_mitre_attack_spec_version") or str(date.today()),
        "attack_version": next(
            (
                o.get("x_mitre_version")
                for o in objects
                if o.get("type") == "x-mitre-collection"
            ),
            "unknown",
        ),
        "description": (
            "Generated by scripts/refresh_playbooks.py from MITRE's official "
            "Enterprise ATT&CK STIX release. Mitigation text is MITRE's own."
        ),
        "source_url": ATTACK_STIX_URL,
        "steps": out_steps,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    print(
        f"[refresh] wrote {len(out_steps)} mitigations "
        f"(ATT&CK v{payload['attack_version']}) -> {OUT_PATH}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
