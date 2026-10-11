from django.db import models
from django.db.models import Q, F

class Plan(models.Model):
    title = models.CharField(max_length=200)
    plan_type = models.CharField(max_length=10, choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('goal', 'Goal')], default='daily')
    start_date = models.DateField()
    end_date = models.DateField()
    proposal = models.JSONField(default=dict)
    constraints = models.JSONField(default=dict)
    status = models.CharField(max_length=12, choices=[(s, s.title()) for s in ['draft', 'approved', 'rejected', 'superseded']], default='draft')
    revision = models.PositiveIntegerField(default=1)
    previous = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(null=True, blank=True)

class ScheduleBlock(models.Model):
    task = models.ForeignKey('tasks.Task', on_delete=models.CASCADE)
    plan = models.ForeignKey(Plan, on_delete=models.CASCADE, related_name='blocks')
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=12, choices=[('scheduled', 'Scheduled'), ('cancelled', 'Cancelled')], default='scheduled')
    class Meta:
        ordering = ['start']
        constraints = [models.CheckConstraint(condition=Q(end__gt=F('start')), name='block_positive_range')]
