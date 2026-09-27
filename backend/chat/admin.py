from django.contrib import admin

from .models import Conversation, ChatMessage


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    fields = ("role", "model", "routing_reason", "created_at")
    readonly_fields = fields


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "document", "updated_at")
    inlines = [ChatMessageInline]
