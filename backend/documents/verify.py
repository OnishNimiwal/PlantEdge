"""
Deterministic answer checks for document answers (no second model / LLM-as-judge).

- Numbers: every numeric value in the answer should appear in the document text.
  Values that do not are reported as "not found in the document" - they may be
  invented, miscopied, or computed (e.g. a difference of two readings).
- Citations: every "[p. N]" citation must refer to a page that was actually given
  to the model.

These checks reduce, but cannot rule out, unsupported answers: a wrong claim that
uses numbers present elsewhere in the document is not detected.
"""

import re

_NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?![\w])")
_CITATION = re.compile(r"\[p\.?\s*(\d+)\]", re.IGNORECASE)
_LIST_MARKER = re.compile(r"^\s*(\d+)[.)]\s", re.MULTILINE)


def _normalise(match):
    whole = match.group(1).replace(",", "")
    frac = match.group(2)
    return f"{int(whole)}.{frac.rstrip('0')}".rstrip(".") if frac else str(int(whole))


def numbers_in(text):
    return {_normalise(m) for m in _NUMBER.finditer(text or "")}


def check_numbers(answer, document_text, question=""):
    """Numbers in the answer that appear nowhere in the document (nor in the question)."""
    cleaned = _CITATION.sub(" ", answer or "")
    cleaned = _LIST_MARKER.sub(" ", cleaned)  # "1. " list numbering is not a claim
    known = numbers_in(document_text) | numbers_in(question)
    missing = sorted(numbers_in(cleaned) - known, key=lambda v: (len(v), v))
    return missing[:10]


def check_citations(answer, pages_available):
    """Cited pages that were not part of what the model was given."""
    cited = {int(n) for n in _CITATION.findall(answer or "")}
    if not pages_available:
        return sorted(cited)
    return sorted(cited - set(pages_available))


def cited_pages(answer):
    return sorted({int(n) for n in _CITATION.findall(answer or "")})
