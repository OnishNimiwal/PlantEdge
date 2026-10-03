"""
Knowledge-base Q&A: answer a question from ALL indexed documents.

    question -> hybrid search in the local Qdrant Edge store (knowledge/search.py)
             -> best sections, labelled [S1], [S2] ... with document, page and classification
             -> local text model (same execution layer and reliability rules as Document Q&A)
             -> checks: values not in the sources, cited labels that were not given,
                answers that cite nothing, confidential sources used

Conversations are stored like other Q&A (Conversation.kind = "knowledge"), so follow-up
questions keep their history. A short follow-up ("and the second one?") is searched
together with the previous question so retrieval has something to go on.
"""

import logging
import re

from django.conf import settings

from chat import context as chat_context
from chat import reliability
from chat.model_manager import chars_per_token, prompt_budget_tokens
from chat.model_registry import get_model
from chat.models import Conversation
from chat.router import route_model
from documents import verify
from documents.models import Document
from documents.retrieval import context_line, tokenize
from documents.services import FORMAT_HINT, NothingToRegenerate, context_budget

from .search import search_sections

logger = logging.getLogger(__name__)

FOLLOW_UP_WORDS = 6
CONFIDENTIAL_NOTICE = "Uses confidential documents: do not share this answer outside the site."
NO_CITATION = "The answer cites no source."
# A cited sentence is flagged when its cited source contains under SUPPORT_MIN of its content
# words while another given source contains at least SUPPORT_MARGIN more (lexical heuristic).
SUPPORT_MIN, SUPPORT_MARGIN, SUPPORT_MIN_WORDS = 0.5, 0.2, 3
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_LABEL = re.compile(r"\[S(\d{1,3})\]")


def _max_sources():
    return int(getattr(settings, "KNOWLEDGE_QA_MAX_SOURCES", 8))


def retrieval_query(conv, question, exclude_ids=()):
    """The question, plus the previous question when this one is a short follow-up."""
    if len(question.split()) > FOLLOW_UP_WORDS:
        return question
    previous = (conv.messages.filter(role="user").exclude(id__in=exclude_ids).order_by("-id")
                .values_list("content", flat=True).first())
    return f"{previous}\n{question}" if previous else question


def _source_header(n, hit):
    doc = hit["document"]
    page = f" · p. {hit['page']}" if hit.get("page") else ""
    return f"[S{n}] {doc.original_name}{page} · {doc.classification}"


def select_sources(hits, budget_chars):
    """Best-first sections that fit the budget -> [{"label", "hit"}]."""
    chosen, used = [], 0
    for hit in hits:
        block = len(hit.get("text") or "") + len(hit.get("heading") or "") + 120
        if used + block > budget_chars:
            continue
        chosen.append(hit)
        used += block
    return [{"label": f"S{i}", "hit": h} for i, h in enumerate(chosen, start=1)]


def sources_block(sources):
    if not sources:
        return "(No indexed document contains information related to this question.)"
    parts = []
    for i, s in enumerate(sources, start=1):
        hit = s["hit"]
        parts.append(f"{_source_header(i, hit)}\n{context_line(hit)}{hit.get('text') or ''}")
    return "\n\n".join(parts)


def source_info(sources):
    """Sources for the client (no full text)."""
    return [{
        "label": s["label"], "document_id": s["hit"]["document"].id,
        "document_name": s["hit"]["document"].original_name, "page": s["hit"].get("page"),
        "section": s["hit"].get("section"), "heading": s["hit"].get("heading"),
        "classification": s["hit"]["document"].classification, "score": round(s["hit"]["score"], 4),
    } for s in sources]


def prepare_knowledge_question(question=None, conversation_id=None, regenerate=False, think=None, language="en",
                               document_ids=None):
    replaced_ids = ()
    if regenerate:
        conv = chat_context.load(conversation_id, create=False, kind=Conversation.KIND_KNOWLEDGE)
        last = chat_context.last_turn(conv) if conv else None
        if not last:
            raise NothingToRegenerate()
        question, replaced_ids = last["message"], last["ids"]
    else:
        conv = chat_context.load(conversation_id, kind=Conversation.KIND_KNOWLEDGE)

    decision = route_model("")  # knowledge answers are text reasoning: the general model
    model_tag = decision["model"]
    window_chars = int(prompt_budget_tokens(get_model(model_tag)) * chars_per_token(get_model(model_tag)))
    budget = context_budget(model_tag, reserved_chars=2000 + len(question) + window_chars // 4)

    query = retrieval_query(conv, question, exclude_ids=replaced_ids)
    hits, method = search_sections(query, document_ids=document_ids, limit=_max_sources())
    sources = select_sources(hits, budget)
    system = reliability.system_prompt(
        "knowledge",
        "You answer questions for an industrial site from its local knowledge base. The sources below are "
        "excerpts from several site documents, most relevant first. Use only these sources. After every fact, "
        "cite the source label in square brackets, e.g. [S2]. If sources disagree, say so and cite each. "
        "If the sources do not contain the answer, say that it was not found in the indexed documents.",
        FORMAT_HINT,
        reliability.language_instruction(language),
        f"=== SOURCES ===\n{sources_block(sources)}\n=== END SOURCES ===",
    )
    messages, history_info = chat_context.build_messages(conv, question, model_tag, system=system,
                                                         exclude_ids=replaced_ids)
    logger.info("Knowledge question: sources=%d documents=%d method=%s history=%d", len(sources),
                len({s["hit"]["document"].id for s in sources}), method, history_info["history_messages_used"])
    return {
        "conv": conv, "question": question, "decision": decision, "messages": messages,
        "replaced_ids": replaced_ids, "sources": sources, "think": think,
        "usage": {"reason": "knowledge", "source": "knowledge", "regenerated": bool(regenerate)},
        "meta": {
            "routing": {"mode": "auto", "reason": "knowledge",
                        "explanation": "question about the local knowledge base: indexed documents, text model"},
            "context": {"retrieval": True, "retrieval_method": method, "retrieval_query": query,
                        "sources_used": len(sources),
                        "documents_used": len({s["hit"]["document"].id for s in sources}), **history_info},
            "sources": source_info(sources),
            "conversation_id": str(conv.id),
            "ollama_model": model_tag,
        },
    }


def miscited(answer, sources):
    """[(cited label, better label)] for sentences whose cited source matches them clearly worse
    than another source that was given to the model."""
    vocab = {i: set(tokenize((s["hit"].get("heading") or "") + " " + (s["hit"].get("text") or "")))
             for i, s in enumerate(sources, start=1)}
    found = []
    for sentence in _SENTENCE.split(answer or ""):
        cited = [int(n) for n in _LABEL.findall(sentence) if int(n) in vocab]
        words = {w for w in tokenize(_LABEL.sub(" ", sentence)) if len(w) > 2}
        if not cited or len(words) < SUPPORT_MIN_WORDS:
            continue
        hits = {i: len(words & v) for i, v in vocab.items()}  # integer counts: no float-rounding edge cases
        best_cited = max(hits[i] for i in cited)
        other = max((i for i in vocab if i not in cited), key=lambda i: hits[i], default=None)
        n = len(words)
        if (other and best_cited < SUPPORT_MIN * n
                and hits[other] - best_cited >= round(SUPPORT_MARGIN * n, 6)):
            pair = (f"S{cited[0]}", f"S{other}")
            if pair not in found:
                found.append(pair)
    return found[:3]


def knowledge_basis(answer, question, sources):
    """Basis indicator + deterministic checks for a knowledge-base answer."""
    cited = verify.cited_sources(answer)
    by_number = {i: s for i, s in enumerate(sources, start=1)}
    used = [by_number[n] for n in cited if n in by_number] or sources
    names = []
    for s in used:
        hit = s["hit"]
        name = hit["document"].original_name + (f" p. {hit['page']}" if hit.get("page") else "")
        if name not in names:
            names.append(name)
    detail = "; ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
    basis = reliability.basis("knowledge", answer, detail if sources else "")
    warnings = []
    if not basis["undetermined"]:
        source_text = "\n".join((s["hit"].get("heading") or "") + "\n" + (s["hit"].get("text") or "") for s in sources)
        missing = verify.check_numbers(answer, source_text, question or "")
        if missing:
            warnings.append(f"Value{'s' if len(missing) > 1 else ''} not found in the sources: {', '.join(missing)}")
        bad = [n for n in cited if n not in by_number]
        if bad:
            warnings.append(f"Cited source{'s' if len(bad) > 1 else ''} not given to the model: "
                            f"{', '.join(f'S{n}' for n in bad)}")
        if sources and not cited:
            warnings.append(NO_CITATION)
        for wrong, better in miscited(answer, sources):
            warnings.append(f"A statement cited to {wrong} matches {better} better: check the citation")
    if any(s["hit"]["document"].classification == Document.CLASS_CONFIDENTIAL for s in used):
        warnings.append(CONFIDENTIAL_NOTICE)
    basis["warnings"] = warnings
    return basis


def finish_knowledge_question(prepared, result):
    """Record the exchange and build the response body."""
    basis = knowledge_basis(result["response"], prepared["question"], prepared["sources"])
    cited = set(verify.cited_sources(result["response"]))
    chat_context.discard(prepared["replaced_ids"])
    user_msg, assistant_msg = chat_context.record_turn(
        prepared["conv"], prepared["question"], result["response"], model_tag=result["ollama_model"],
        reason="knowledge", basis=basis,
    )
    return {
        "answer": result["response"],
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
        "model": result["model"],
        "ollama_model": result["ollama_model"],
        "basis": basis,
        **prepared["meta"],
        # the final event marks which sources the answer actually cites
        "sources": [{**s, "cited": int(s["label"][1:]) in cited} for s in prepared["meta"]["sources"]],
    }
