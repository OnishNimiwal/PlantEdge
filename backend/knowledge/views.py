"""
Local knowledge store API.

GET  /api/knowledge/status/          store + per-document index state
POST /api/knowledge/search/          {"query", "document_ids"?, "limit"?} hybrid search across documents
POST /api/knowledge/reindex/         {"document_ids"?, "force"?} queue (re)indexing on the document worker
POST /api/knowledge/ask/             {"question" | "regenerate", "conversation_id"?, "document_ids"?, ...}
POST /api/knowledge/ask/stream/      streaming variant (NDJSON, same events as document Q&A)
GET  /api/knowledge/policy/          classification levels, default, override setting
GET  /api/knowledge/egress-review/   what would leave the site now (nothing is sent or audited)
GET  /api/knowledge/policy-events/   classification / egress audit trail
POST /api/documents/<id>/classification/  {"classification", "reason"?, "override"?}
"""

from django.conf import settings
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from chat.model_manager import ModelManager, ModelManagerError, generate_response, loaded_models
from chat.views import StreamNegotiation, ndjson_stream, streaming_response
from documents import jobs
from documents.models import Document
from documents.serializers import DocumentAskSerializer, DocumentDetailSerializer
from documents.services import NothingToRegenerate

from . import embeddings, indexing, policy, store
from .models import PolicyEvent
from .qa import finish_knowledge_question, prepare_knowledge_question
from .search import search

MAX_QUERY_CHARS = 1000
MAX_LIMIT = 20


class KnowledgeStatusView(APIView):
    def get(self, request):
        by_status = dict(Document.objects.filter(status=Document.STATUS_READY)
                         .values_list("index_status").annotate(n=Count("id")))
        return Response({
            "success": True,
            "enabled": indexing.enabled(),
            "store": store.info(),
            "embedding": {"model": embeddings.model_name(), "device": settings.EMBEDDING_DEVICE},
            "documents": {
                "ready": sum(by_status.values()),
                "indexed": by_status.get(Document.INDEX_INDEXED, 0),
                "pending": by_status.get(Document.INDEX_PENDING, 0),
                "failed": by_status.get(Document.INDEX_FAILED, 0),
                "needs_indexing": len(indexing.pending_documents()),
            },
        })


class KnowledgeSearchView(APIView):
    def post(self, request):
        query = str(request.data.get("query") or "").strip()
        if not query:
            return Response({"success": False, "error": "Enter a search query."}, status=status.HTTP_400_BAD_REQUEST)
        if len(query) > MAX_QUERY_CHARS:
            return Response({"success": False, "error": f"The query is longer than {MAX_QUERY_CHARS} characters."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            limit = max(1, min(int(request.data.get("limit") or 8), MAX_LIMIT))
            ids = [int(i) for i in request.data.get("document_ids") or []]
        except (TypeError, ValueError):
            return Response({"success": False, "error": "Invalid limit or document_ids."},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            hits, method = search(query, document_ids=ids or None, limit=limit)
        except store.StoreError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"success": True, "query": query, "method": method, "results": hits})


class KnowledgeReindexView(APIView):
    def post(self, request):
        if not indexing.enabled():
            return Response({"success": False, "error": "Knowledge indexing is turned off (KNOWLEDGE_INDEXING)."},
                            status=status.HTTP_409_CONFLICT)
        force = bool(request.data.get("force"))
        try:
            ids = [int(i) for i in request.data.get("document_ids") or []]
        except (TypeError, ValueError):
            return Response({"success": False, "error": "Invalid document_ids."}, status=status.HTTP_400_BAD_REQUEST)
        ready = Document.objects.filter(status=Document.STATUS_READY).exclude(extracted_text="")
        if ids:
            ready = ready.filter(id__in=ids)
            targets = list(ready.values_list("id", flat=True))
        else:
            targets = list(ready.values_list("id", flat=True)) if force else indexing.pending_documents()
        jobs.submit_index(targets, force=force)
        return Response({"success": True, "queued": len(targets), "document_ids": targets},
                        status=status.HTTP_202_ACCEPTED)


def client_address(request):
    """The connecting address, for the audit trail (proxy headers are not trusted)."""
    return request.META.get("REMOTE_ADDR", "")[:64]


class KnowledgeAskSerializer(DocumentAskSerializer):
    document_ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False,
                                         allow_empty=True, max_length=200)


def _prepare(request):
    """(prepared, None) or (None, error Response) for both ask endpoints."""
    serializer = KnowledgeAskSerializer(data=request.data)
    if not serializer.is_valid():
        return None, Response({"success": False, "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
    v = serializer.validated_data
    try:
        return prepare_knowledge_question(v.get("question"), v.get("conversation_id"), v["regenerate"],
                                          v.get("think"), v.get("language", "en"),
                                          document_ids=v.get("document_ids") or None), None
    except NothingToRegenerate:
        return None, Response({"success": False, "error": "There is no answer to regenerate."},
                              status=status.HTTP_400_BAD_REQUEST)
    except store.StoreError as exc:
        return None, Response({"success": False, "error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class KnowledgeAskView(APIView):
    def post(self, request):
        prepared, error = _prepare(request)
        if error is not None:
            return error
        try:
            result = generate_response(prepared["decision"]["model"], messages=prepared["messages"],
                                       usage=prepared["usage"], think=prepared["think"])
        except ModelManagerError as exc:
            return Response({"success": False, "error": exc.public_message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"success": True, **finish_knowledge_question(prepared, result), "external_api": False})


class KnowledgeAskStreamView(APIView):
    content_negotiation_class = StreamNegotiation

    def post(self, request):
        prepared, error = _prepare(request)
        if error is not None:
            return error
        try:
            model_loading = prepared["decision"]["model"] not in loaded_models()
            opened = ModelManager().chat_stream(prepared["decision"]["model"], prepared["messages"],
                                                usage=prepared["usage"], think=prepared["think"])
        except ModelManagerError as exc:
            return Response({"success": False, "error": exc.public_message}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return streaming_response(ndjson_stream(
            opened, {**prepared["meta"], "model_loading": model_loading},
            lambda event: finish_knowledge_question(prepared, event),
        ), opened)


class PolicyView(APIView):
    def get(self, request):
        return Response({
            "levels": [{"id": level, "description": policy.DESCRIPTIONS[level],
                        "may_leave_site": policy.may_leave_site(level)} for level in policy.LEVELS],
            "default": policy.default_level(),
            "allow_override": bool(getattr(settings, "CLASSIFICATION_ALLOW_OVERRIDE", False)),
        })


class DocumentClassificationView(APIView):
    def post(self, request, pk):
        doc = get_object_or_404(Document, pk=pk)
        data = request.data if isinstance(request.data, dict) else {}
        try:
            policy.change_classification(doc, str(data.get("classification") or ""), str(data.get("reason") or ""),
                                         override=data.get("override") is True, client=client_address(request))
        except policy.PolicyError as exc:
            refused = isinstance(exc, policy.PolicyRefused)
            return Response({"success": False, "error": str(exc)},
                            status=status.HTTP_403_FORBIDDEN if refused else status.HTTP_400_BAD_REQUEST)
        doc.refresh_from_db()
        return Response({"success": True, "document": DocumentDetailSerializer(doc).data})


class EgressReviewView(APIView):
    def get(self, request):
        try:
            return Response({"success": True, **policy.egress_review()})
        except store.StoreError as exc:
            return Response({"success": False, "error": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


class PolicyEventsView(APIView):
    def get(self, request):
        try:
            limit = max(1, min(int(request.query_params.get("limit", 50)), 500))
            document = int(request.query_params["document"]) if request.query_params.get("document") else None
        except ValueError:
            return Response({"success": False, "error": "Invalid limit or document."},
                            status=status.HTTP_400_BAD_REQUEST)
        qs = PolicyEvent.objects.all()
        if request.query_params.get("event"):
            qs = qs.filter(event=request.query_params["event"])
        if document is not None:
            qs = qs.filter(document_id=document)
        return Response({"events": [{
            "id": e.id, "event": e.event, "document_id": e.document_id, "document_name": e.document_name,
            "from_level": e.from_level, "to_level": e.to_level, "reason": e.reason, "detail": e.detail,
            "client": e.client, "created_at": e.created_at,
        } for e in qs[:limit]]})
