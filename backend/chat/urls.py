from django.urls import path
from .views import ChatAPIView, RouteAPIView

urlpatterns = [
    path("", ChatAPIView.as_view(), name="chat"),
    path("route/", RouteAPIView.as_view(), name="chat-route"),
]
