from django.contrib import admin
from tasks.admin import TaskAdmin
from .models import Plan, ScheduleBlock

@admin.register(Plan)
class PlanAdmin(TaskAdmin):
    list_display = ['title', 'status', 'revision', 'created_at']

@admin.register(ScheduleBlock)
class BlockAdmin(TaskAdmin):
    list_display = ['task', 'start', 'end', 'status']
