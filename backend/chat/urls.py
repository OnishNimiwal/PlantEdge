from django.urls import path
from .views import ChatAPIView, RouteAPIView, ConversationListAPIView, ConversationDetailAPIView

urlpatterns = [
    path("", ChatAPIView.as_view(), name="chat"),
    path("route/", RouteAPIView.as_view(), name="chat-route"),
    path("conversations/", ConversationListAPIView.as_view(), name="conversation-list"),
    path("conversations/<uuid:pk>/", ConversationDetailAPIView.as_view(), name="conversation-detail"),
]
