from typing import Annotated
from pydantic import Field
from langchain_core.tools import tool
from django.utils import timezone
from tasks.models import Task, Goal
from tasks.serializers import TaskSerializer, GoalSerializer
from planner.schemas import PlanInput
from planner.services import priority_score, create_plan
from analytics.services import summary
from .operations import proposal_plan
from .schemas import TaskProposal

Id = Annotated[int, Field(gt=0)]

@tool
def list_tasks(status: str = '', limit: Annotated[int, Field(ge=1, le=100)] = 50) -> dict:
    """Read saved tasks, optionally filtered by status. Returns bounded records and total count."""
    qs = Task.objects.all()
    if status:
        if status not in ['pending', 'in_progress', 'completed', 'cancelled']:
            return {'error': 'Invalid status.'}
        qs = qs.filter(status=status)
    return {'total': qs.count(), 'tasks': TaskSerializer(qs[:limit], many=True).data}

@tool
def get_task_details(task_id: Id) -> dict:
    """Read one saved task by ID."""
    task = Task.objects.filter(pk=task_id).first()
    return TaskSerializer(task).data if task else {'error': 'Task not found.'}

@tool
def create_task(task: TaskProposal) -> dict:
    """Propose a new task for human approval. Does not create the task yet."""
    plan = proposal_plan([{'kind': 'create_task', 'data': task.model_dump(mode='json')}])
    return {'plan_id': plan.pk, 'status': 'draft', 'approval_required': True}

@tool
def update_task(task_id: Id, changes: dict) -> dict:
    """Propose validated changes to one existing task for human approval."""
    if not Task.objects.filter(pk=task_id).exists():
        return {'error': 'Task not found.'}
    plan = proposal_plan([{'kind': 'update_task', 'task_id': task_id, 'data': changes}])
    return {'plan_id': plan.pk, 'status': 'draft', 'approval_required': True}

@tool
def complete_task(task_id: Id) -> dict:
    """Propose marking a task completed; explicit human approval is required."""
    if not Task.objects.filter(pk=task_id).exists():
        return {'error': 'Task not found.'}
    plan = proposal_plan([{'kind': 'complete_task', 'task_id': task_id}])
    return {'plan_id': plan.pk, 'status': 'draft', 'approval_required': True}

@tool
def get_overdue_tasks() -> dict:
    """Read overdue active tasks using the current clock."""
    qs = Task.objects.filter(status__in=['pending', 'in_progress'], deadline__lt=timezone.now())
    return {'total': qs.count(), 'tasks': TaskSerializer(qs[:100], many=True).data}

@tool
def list_goals() -> dict:
    """Read saved goals."""
    return {'goals': GoalSerializer(Goal.objects.order_by('pk')[:100], many=True).data}

@tool
def get_available_time(constraints: PlanInput) -> dict:
    """Inspect explicitly supplied availability and existing approved commitments. Do not invent availability."""
    from planner.services import available_time
    return available_time(constraints.model_dump(mode='json'))

@tool
def calculate_priority(task_id: Id) -> dict:
    """Calculate deterministic priority from importance, deadline pressure, and effort."""
    task = Task.objects.filter(pk=task_id).first()
    return {'task_id': task_id, 'score': priority_score(task)} if task else {'error': 'Task not found.'}

@tool
def generate_plan(constraints: PlanInput) -> dict:
    """Generate a draft schedule with deterministic feasibility checks, requiring approval."""
    plan = create_plan(constraints.model_dump(mode='json'), source='agent')
    return {'plan_id': plan.pk, 'status': 'draft', 'proposal': plan.proposal}

@tool
def get_productivity_summary() -> dict:
    """Read computed productivity facts from saved records."""
    return summary()

TOOLS = [list_tasks, get_task_details, create_task, update_task, complete_task, get_overdue_tasks,
         list_goals, get_available_time, calculate_priority, generate_plan, get_productivity_summary]
