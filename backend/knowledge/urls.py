from django.urls import path

from .views import (
    EgressReviewView, KnowledgeAskStreamView, KnowledgeAskView, KnowledgeReindexView, KnowledgeSearchView,
    KnowledgeStatusView, PolicyEventsView, PolicyView,
)

urlpatterns = [
    path("status/", KnowledgeStatusView.as_view(), name="knowledge-status"),
    path("search/", KnowledgeSearchView.as_view(), name="knowledge-search"),
    path("reindex/", KnowledgeReindexView.as_view(), name="knowledge-reindex"),
    path("ask/", KnowledgeAskView.as_view(), name="knowledge-ask"),
    path("ask/stream/", KnowledgeAskStreamView.as_view(), name="knowledge-ask-stream"),
    path("policy/", PolicyView.as_view(), name="knowledge-policy"),
    path("egress-review/", EgressReviewView.as_view(), name="knowledge-egress-review"),
    path("policy-events/", PolicyEventsView.as_view(), name="knowledge-policy-events"),
]
