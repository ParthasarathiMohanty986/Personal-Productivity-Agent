from collections import Counter
from datetime import timedelta, datetime
from django.utils import timezone
from tasks.models import Task, ActivityLog

def summary():
    from planner.services import schedule_issues
    tasks = list(Task.objects.all())
    now = timezone.now()
    completed = [t for t in tasks if t.status == 'completed']
    measured = [t for t in completed if t.actual_minutes is not None and t.estimated_minutes is not None]
    postponed = set()
    for event in ActivityLog.objects.filter(action='task.updated'):
        old, new = event.details.get('previous_deadline'), event.details.get('deadline')
        if old and new and datetime.fromisoformat(new) > datetime.fromisoformat(old):
            postponed.add(event.task_id or event.details.get('id'))
    active = [t for t in tasks if t.status in ['pending', 'in_progress']]
    eligible = [t for t in tasks if t.status != 'cancelled']
    return {'generated_at': now.isoformat(), 'total': len(tasks), 'completed': len(completed),
        'completion_rate': round(100 * len(completed) / len(eligible), 1) if eligible else 0,
        'overdue': sum(bool(t.deadline and t.deadline < now) for t in active),
        'status_distribution': dict(Counter(t.status for t in tasks)),
        'priority_breakdown': dict(Counter(t.priority for t in tasks)),
        'estimated_vs_actual': {'sample_count': len(measured), 'estimated_minutes': sum(t.estimated_minutes for t in measured),
            'actual_minutes': sum(t.actual_minutes for t in measured)} if measured else None,
        'postponed_tasks': len(postponed), 'postponed_basis': 'Recorded deadline extensions only',
        'schedule_issues': schedule_issues(),
        'facts': f'{len(completed)} of {len(eligible)} non-cancelled tasks are currently completed.'}

def trends():
    today = timezone.localdate()
    tasks = list(Task.objects.all())
    daily = []
    for offset in range(13, -1, -1):
        day = today - timedelta(days=offset)
        daily.append({'date': day.isoformat(), 'created': sum(timezone.localdate(t.created_at) == day for t in tasks),
            'completed': sum(bool(t.completed_at and timezone.localdate(t.completed_at) == day) for t in tasks)})
    return {'daily': daily, 'weekly': [{'label': 'Previous 7 days', 'completed': sum(d['completed'] for d in daily[:7])},
        {'label': 'Latest 7 days', 'completed': sum(d['completed'] for d in daily[7:])}],
        'basis': 'Current task records; deleted tasks are excluded.'}

def report():
    return {'summary': summary(), 'trends': trends()}
