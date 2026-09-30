"""
Section retrieval for long documents (local, deterministic - no embeddings, no vector DB).

When a document does not fit the model's context window, it is split into
sections of ~1,200 characters (on paragraph boundaries), each labelled with the
PDF page it starts on, and the sections most relevant to the question are chosen
with BM25 keyword ranking. Selected sections keep their original order and are
labelled "[p. N]" so the model can cite pages and the citations can be checked.

Short documents are passed whole (still page-labelled when page offsets exist).
"""

import bisect
import math
import re
from collections import Counter

SECTION_CHARS = 1200
_TOKEN = re.compile(r"[a-z0-9]+(?:[.\-/][a-z0-9]+)*", re.IGNORECASE)
_STOPWORDS = set(
    "a an the and or of to in on for at by with from is are was were be been this that these those it its "
    "what which who whom whose when where why how does do did can could should would will shall may might "
    "about into than then there their them they you your we our i me my please tell give list show find "
    "document report file".split()
)


def _tokens(text):
    return [t.lower() for t in _TOKEN.findall(text or "") if t.lower() not in _STOPWORDS]


def _page_at(offsets, pos):
    """Page number whose text starts at or before character `pos` (offsets: [[page, start], ...])."""
    if not offsets:
        return None
    starts = [start for _, start in offsets]
    i = bisect.bisect_right(starts, pos) - 1
    return offsets[max(i, 0)][0]


def split_sections(text, offsets=None, size=SECTION_CHARS):
    """[{"start", "text", "page"}] in document order; section boundaries prefer paragraph and page breaks."""
    text = text or ""
    breaks = sorted({start for _, start in (offsets or [])} | {0})
    sections, pos = [], 0
    while pos < len(text):
        end = min(pos + size, len(text))
        # never run a section across a page start
        next_page = next((b for b in breaks if pos < b < end), None)
        if next_page is not None:
            end = next_page
        elif end < len(text):
            cut = text.rfind("\n\n", pos + size // 2, end)
            if cut == -1:
                cut = text.rfind("\n", pos + size // 2, end)
            if cut > pos:
                end = cut
        chunk = text[pos:end].strip()
        if chunk:
            sections.append({"start": pos, "text": chunk, "page": _page_at(offsets, pos)})
        pos = end
    return sections


def bm25_rank(sections, query, k1=1.5, b=0.75):
    """Section indexes sorted by BM25 relevance to `query` (ties keep document order)."""
    q = set(_tokens(query))
    docs = [_tokens(s["text"]) for s in sections]
    if not q or not docs:
        return list(range(len(sections)))
    avg = sum(len(d) for d in docs) / len(docs) or 1
    df = Counter(t for d in docs for t in set(d))
    n = len(docs)
    scores = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if tf[t]:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        scores.append((s, i))
    return [i for _, i in sorted(scores, key=lambda x: (-x[0], x[1]))]


def _label(section):
    return f"[p. {section['page']}] " if section["page"] else ""


def _spread(sections, budget_chars):
    """Evenly spaced sections across the whole document (for summaries)."""
    total = len(sections)
    if not total:
        return []
    avg = sum(len(s["text"]) + 12 for s in sections) / total
    k = max(1, min(total, int(budget_chars // avg)))
    step = total / k
    return sorted({min(total - 1, int(i * step)) for i in range(k)})


def build_context(text, question, budget_chars, offsets=None):
    """
    Document content for the prompt, within `budget_chars`.
    Returns (content, info) with info = {document_chars, context_chars_used, context_truncated,
    retrieval, sections_used, sections_total, pages}.
    """
    text = text or ""
    sections = split_sections(text, offsets)
    labelled = bool(offsets)
    info = {"document_chars": len(text), "sections_total": len(sections), "retrieval": False}

    def render(chosen):
        return "\n\n".join(f"{_label(sections[i]) if labelled else ''}{sections[i]['text']}" for i in chosen)

    everything = render(range(len(sections)))
    if len(everything) <= budget_chars:
        chosen = list(range(len(sections)))
        content = everything
    elif not question:
        # No question (summary): cover the whole document with evenly spaced sections.
        chosen = _spread(sections, budget_chars)
        while chosen and sum(len(sections[i]["text"]) + 12 for i in chosen) > budget_chars:
            chosen.pop()
        content = render(chosen)
        info["retrieval"] = True
        content += (f"\n\n[{len(chosen)} sections spread across the document are shown; "
                    f"{len(sections) - len(chosen)} other section(s) were not included.]")
    else:
        ranked = bm25_rank(sections, question)
        chosen, used = [], 0
        # the opening section (title, metadata) is kept when it fits: it usually identifies the document
        for i in ([0] if sections else []) + ranked:
            if i in chosen:
                continue
            cost = len(sections[i]["text"]) + 12
            if used + cost > budget_chars:
                continue
            chosen.append(i)
            used += cost
        chosen.sort()
        content = render(chosen)
        info["retrieval"] = True
        omitted = len(sections) - len(chosen)
        content += (f"\n\n[Only the {len(chosen)} sections most relevant to the question are shown; "
                    f"{omitted} other section(s) of the document were not included.]")
    info.update({
        "context_chars_used": sum(len(sections[i]["text"]) for i in chosen),
        "context_truncated": info["retrieval"],
        "sections_used": len(chosen),
        "pages": sorted({sections[i]["page"] for i in chosen if sections[i]["page"]}),
    })
    return content, info
