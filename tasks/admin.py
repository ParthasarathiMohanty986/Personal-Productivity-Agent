from django.contrib import admin
from .models import Task, Goal, ActivityLog

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'status', 'priority', 'deadline']
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

@admin.register(Goal)
class GoalAdmin(TaskAdmin):
    list_display = ['title', 'status', 'target_date']

@admin.register(ActivityLog)
class ActivityAdmin(TaskAdmin):
    list_display = ['action', 'source', 'created_at']
