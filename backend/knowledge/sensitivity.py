"""
Content scan for sensitive information (deterministic rules, no model).

Used twice: after text extraction (raises a document's classification when needed) and
again on every section at egress time (knowledge/policy.py), so content that the rules
catch can never leave the site even if a document was labelled shareable.

Only the kind of finding and how often it occurs are reported - never the matched
values, so the scan result itself is safe to store, log and show.

The rules are conservative: a false positive keeps data on site (safe); a false
negative is what the classification label and human review are for.
"""

import re

from documents.models import Document

CONF, INTERNAL = Document.CLASS_CONFIDENTIAL, Document.CLASS_INTERNAL

# (type, label, pattern, minimum classification when found)
RULES = [
    ("marking", "Confidentiality marking", re.compile(r"\b(?:strictly\s+)?confidential\b", re.I), CONF),
    ("marking", "Proprietary / trade secret marking", re.compile(r"\b(?:proprietary|trade\s+secrets?)\b", re.I), CONF),
    ("marking", "Distribution restriction",
     re.compile(r"\b(?:internal\s+use\s+only|not\s+for\s+(?:external\s+)?distribution|"
                r"do\s+not\s+(?:distribute|share|forward|copy))\b", re.I), CONF),
    ("personal_data", "Email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), CONF),
    ("personal_data", "Phone number", re.compile(r"(?<!\d)(?<!\d\.)(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d|\.\d)"), CONF),
    ("personal_data", "Aadhaar number", re.compile(r"(?<!\d)[2-9]\d{3}[\s-]\d{4}[\s-]\d{4}(?!\d)"), CONF),
    ("personal_data", "PAN number", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), CONF),
    ("credential", "Password or secret",
     re.compile(r"\b(?:password|passwd|pwd|secret|api[_\s-]?key|access[_\s-]?token)\s*[:=]\s*\S+", re.I), CONF),
    ("credential", "Private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), CONF),
    ("credential", "Cloud access key", re.compile(r"\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,})\b"), CONF),
    ("network", "Internal network address",
     re.compile(r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"),
     INTERNAL),
]


def scan(text):
    """[{"type", "label", "count", "min_level"}] for every rule that matches `text`."""
    found = []
    for kind, label, pattern, level in RULES:
        count = len(pattern.findall(text or ""))
        if count:
            found.append({"type": kind, "label": label, "count": count, "min_level": level})
    return found


def summary(markers):
    """'Email address (2), Confidentiality marking' for messages and audit reasons."""
    parts = []
    for m in markers:
        parts.append(f"{m['label']} ({m['count']})" if m["count"] > 1 else m["label"])
    return ", ".join(parts)
