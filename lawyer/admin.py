from django.contrib import admin
from .models import BaseDocument, Case, Conversation, Message, FlowCase

@admin.register(FlowCase)
class FlowCaseAdmin(admin.ModelAdmin):
    list_display = ('case', 'objective', 'is_active', 'is_completed', 'created_at', 'updated_at')
    list_filter = ('is_active', 'is_completed', 'created_at')
    search_fields = ('case__title', 'objective', 'issues', 'facts', 'avenues', 'conclusion')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Case Information', {
            'fields': ('case', 'objective')
        }),
        ('Analysis', {
            'fields': ('issues', 'facts', 'avenues', 'conclusion')
        }),
        ('Status', {
            'fields': ('is_active', 'is_completed')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

admin.site.register(BaseDocument)
admin.site.register(Case)
admin.site.register(Conversation)
admin.site.register(Message)
