from django.urls import path

from .views import UsageDashboardView, SystemStatusView, DeepCheckView

urlpatterns = [
    path("usage/", UsageDashboardView.as_view(), name="dashboard-usage"),
    path("status/", SystemStatusView.as_view(), name="dashboard-status"),
    path("deep-check/", DeepCheckView.as_view(), name="dashboard-deep-check"),
]
