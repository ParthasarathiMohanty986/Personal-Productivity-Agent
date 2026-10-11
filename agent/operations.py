from django.core.exceptions import ValidationError
from django.utils import timezone
from tasks.models import Task
from tasks.serializers import TaskSerializer, GoalSerializer
from tasks.services import save_task, save_goal, log
from planner.models import Plan
from .schemas import Operation, Extraction

def validate_operations(raw):
    if not isinstance(raw, list) or not 1 <= len(raw) <= 70:
        raise ValidationError('A proposal must contain 1 to 70 operations.')
    operations = [Operation.model_validate(o) for o in raw]
    goals = [o for o in operations if o.kind == 'create_goal']
    creates = [o for o in operations if o.kind == 'create_task']
    for op in operations:
        data = dict(op.data)
        if op.kind == 'create_goal':
            serializer = GoalSerializer(data=data)
        elif op.kind == 'create_task':
            gi = data.pop('goal_index', None)
            deps = data.pop('dependency_indices', [])
            if gi is not None and (not isinstance(gi, int) or not 0 <= gi < len(goals)):
                raise ValidationError('Unknown goal reference.')
            if not isinstance(deps, list) or any(not isinstance(i, int) or not 0 <= i < len(creates) for i in deps):
                raise ValidationError('Unknown dependency reference.')
            data.pop('estimate_uncertain', None)
            serializer = TaskSerializer(data=data)
        else:
            task = Task.objects.filter(pk=op.task_id).first()
            if task is None:
                raise ValidationError('Task no longer exists.')
            if op.kind == 'complete_task':
                data = {'status': 'completed'}
            serializer = TaskSerializer(task, data=data, partial=True)
        writable = {k for k, v in serializer.fields.items() if not v.read_only}
        if set(data) - writable:
            raise ValidationError('Unknown or read-only task/goal fields.')
        serializer.is_valid(raise_exception=True)
    edges = [o.data.get('dependency_indices', []) for o in creates]
    def visit(i, path):
        if i in path:
            raise ValidationError('Task dependencies form a cycle.')
        for j in edges[i]:
            visit(j, path | {i})
    for i in range(len(edges)):
        visit(i, set())
    return operations

def apply_operations(raw):
    operations = validate_operations(raw)
    goals, created = [], []
    for op in operations:
        if op.kind == 'create_goal':
            goals.append(save_goal(op.data, source='agent'))
    for op in operations:
        if op.kind == 'create_task':
            data = dict(op.data)
            gi = data.pop('goal_index', None)
            data.pop('dependency_indices', None)
            data.pop('estimate_uncertain', None)
            if gi is not None:
                data['goal'] = goals[gi].pk
            created.append(save_task(data, source='agent'))
    for task, op in zip(created, [o for o in operations if o.kind == 'create_task']):
        if op.data.get('dependency_indices'):
            save_task({'dependencies': [created[i].pk for i in op.data['dependency_indices']]}, task, source='agent')
    for op in operations:
        if op.kind in ['update_task', 'complete_task']:
            data = {'status': 'completed'} if op.kind == 'complete_task' else op.data
            save_task(data, Task.objects.get(pk=op.task_id), source='agent')

def proposal_plan(operations, title='Review proposed task changes', warnings=None):
    validate_operations(operations)
    today = timezone.localdate()
    plan = Plan.objects.create(title=title, plan_type='goal', start_date=today, end_date=today,
        proposal={'operations': operations, 'blocks': [], 'unscheduled': [], 'warnings': warnings or []})
    log('plan.proposed', title, 'agent', plan=plan)
    return plan

def extraction_plan(extraction):
    extraction = Extraction.model_validate(extraction)
    if extraction.clarifications:
        return None
    operations = [{'kind': 'create_goal', 'data': g.model_dump(mode='json')} for g in extraction.goals]
    operations += [{'kind': 'create_task', 'data': t.model_dump(mode='json')} for t in extraction.tasks]
    if not operations:
        return None
    warnings = extraction.recurring_requirements + extraction.availability_constraints
    if any(t.estimate_uncertain for t in extraction.tasks):
        warnings.append('Some durations are AI estimates. Review them before approval.')
    return proposal_plan(operations, warnings=warnings)
