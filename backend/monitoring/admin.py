from django.contrib import admin

from .models import UsageRecord


@admin.register(UsageRecord)
class UsageRecordAdmin(admin.ModelAdmin):
    list_display = ("created_at", "model", "category", "source", "success", "error_type", "duration_ms")
    list_filter = ("model", "category", "success", "source")
