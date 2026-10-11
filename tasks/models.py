from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

STATUS = [(v, v.replace('_', ' ').title()) for v in ['pending', 'in_progress', 'completed', 'cancelled']]
PRIORITY = [(v, v.title()) for v in ['low', 'medium', 'high', 'urgent']]

class Goal(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, max_length=5000)
    target_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class Task(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, max_length=5000)
    status = models.CharField(max_length=20, choices=STATUS, default='pending', db_index=True)
    priority = models.CharField(max_length=10, choices=PRIORITY, default='medium')
    category = models.CharField(max_length=100, blank=True)
    deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    estimated_minutes = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(10080)])
    actual_minutes = models.PositiveIntegerField(null=True, blank=True, validators=[MaxValueValidator(10080)])
    goal = models.ForeignKey(Goal, null=True, blank=True, on_delete=models.SET_NULL, related_name='tasks')
    dependencies = models.ManyToManyField('self', symmetrical=False, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-pk']

class ActivityLog(models.Model):
    action = models.CharField(max_length=50)
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.SET_NULL)
    plan = models.ForeignKey('planner.Plan', null=True, blank=True, on_delete=models.SET_NULL)
    description = models.CharField(max_length=500)
    details = models.JSONField(default=dict)
    source = models.CharField(max_length=10, choices=[('user', 'User'), ('api', 'API'), ('agent', 'Agent')])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
