from django.urls import path

from .views import UsageDashboardView, SystemStatusView

urlpatterns = [
    path("usage/", UsageDashboardView.as_view(), name="dashboard-usage"),
    path("status/", SystemStatusView.as_view(), name="dashboard-status"),
]
