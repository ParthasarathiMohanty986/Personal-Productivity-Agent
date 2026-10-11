from django.db import transaction
from django.utils import timezone
from .models import Task, Goal, ActivityLog
from .serializers import TaskSerializer, GoalSerializer

def log(action, description, source='api', task=None, plan=None, details=None):
    return ActivityLog.objects.create(action=action, description=description, source=source, task=task, plan=plan, details=details or {})

@transaction.atomic
def save_task(data, instance=None, source='api'):
    serializer = TaskSerializer(instance, data=data, partial=instance is not None)
    serializer.is_valid(raise_exception=True)
    old_deadline = instance.deadline.isoformat() if instance and instance.deadline else None
    status = serializer.validated_data.get('status', instance.status if instance else 'pending')
    completed_at = (instance.completed_at if instance and instance.completed_at else timezone.now()) if status == 'completed' else None
    task = serializer.save(completed_at=completed_at)
    log('task.updated' if instance else 'task.created', f'{task.title}: {task.status}', source, task=task,
        details={'previous_deadline': old_deadline, 'deadline': task.deadline.isoformat() if task.deadline else None})
    return task

@transaction.atomic
def save_goal(data, instance=None, source='api'):
    serializer = GoalSerializer(instance, data=data, partial=instance is not None)
    serializer.is_valid(raise_exception=True)
    goal = serializer.save()
    log('goal.updated' if instance else 'goal.created', goal.title, source, details={'goal_id': goal.pk})
    return goal

@transaction.atomic
def delete_record(instance, source='api'):
    log(f'{instance.__class__.__name__.lower()}.deleted', instance.title, source, details={'id': instance.pk})
    instance.delete()
