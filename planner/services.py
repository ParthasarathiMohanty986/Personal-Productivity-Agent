from datetime import datetime, timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from tasks.models import Task
from tasks.services import log
from .models import Plan, ScheduleBlock
from .schemas import PlanInput, ProposedBlock

ACTIVE = ['pending', 'in_progress']

def priority_score(task, now=None):
    now = now or timezone.now()
    importance = {'low': 10, 'medium': 25, 'high': 40, 'urgent': 60}[task.priority]
    urgency = 0
    if task.deadline:
        hours = (task.deadline - now).total_seconds() / 3600
        urgency = 60 if hours <= 0 else max(0, 48 - hours) + min(20, (task.estimated_minutes or 0) / max(hours * 60, 1) * 20)
    return round(importance + urgency, 2)

def overlap(start, end, other_start, other_end):
    return start < other_end and end > other_start

def approved_blocks(exclude_plan=None):
    qs = ScheduleBlock.objects.filter(status='scheduled', plan__status='approved', task__status__in=ACTIVE)
    if exclude_plan:
        qs = qs.exclude(plan_id=exclude_plan)
    return qs

def replacement_target(plan):
    """Follow draft revision chains to the approved schedule they would replace."""
    previous = plan.previous
    while previous:
        if previous.approved_at:
            if previous.status != 'approved':
                raise ValidationError('Another revision already replaced the original schedule.')
            return previous
        previous = previous.previous
    return None

def available_time(inputs):
    config = PlanInput.model_validate(inputs)
    tz, now = timezone.get_current_timezone(), timezone.now()
    commitments = list(approved_blocks())
    occupied = [(b.start, b.end) for b in commitments] + [(b.start, b.end) for b in config.busy]
    days = []
    for offset in range((config.end_date-config.start_date).days+1):
        day = config.start_date + timedelta(days=offset)
        if day.weekday() not in config.weekdays:
            continue
        start, end = max(datetime.combine(day,config.day_start,tz), now), datetime.combine(day,config.day_end,tz)
        cursor, free = start, []
        for a, b in sorted(occupied):
            if b <= cursor or a >= end:
                continue
            if a > cursor:
                free.append((cursor, min(a,end)))
            cursor = max(cursor,b)
        if cursor < end:
            free.append((cursor,end))
        committed = sum((b.end-b.start).total_seconds()/60 for b in commitments if timezone.localdate(b.start)==day)
        remaining = max(0, config.daily_minutes-committed)
        free_minutes = sum((b-a).total_seconds()/60 for a,b in free)
        days.append({'date':str(day), 'free_windows':[{'start':a.isoformat(),'end':b.isoformat()} for a,b in free],
            'available_minutes':min(remaining,free_minutes), 'remaining_focus_capacity':remaining})
    return {'days':days,'total_available_minutes':sum(d['available_minutes'] for d in days)}

def schedule_issues():
    """Report commitments invalidated by later task edits without modifying them."""
    blocks = list(approved_blocks().select_related('task'))
    issues = []
    for index, block in enumerate(blocks):
        if block.task.deadline and block.end > block.task.deadline:
            issues.append({'task_id':block.task_id, 'plan_id':block.plan_id, 'reason':'Approved block ends after the current deadline.'})
        if block.task.estimated_minutes != (block.end-block.start).total_seconds()/60:
            issues.append({'task_id':block.task_id, 'plan_id':block.plan_id, 'reason':'Task estimate differs from its approved block.'})
        if block.end < timezone.now():
            issues.append({'task_id':block.task_id, 'plan_id':block.plan_id, 'reason':'Scheduled time passed; task is still incomplete.'})
        for other in blocks[index+1:]:
            if overlap(block.start,block.end,other.start,other.end):
                issues.append({'task_id':block.task_id, 'plan_id':block.plan_id, 'reason':f'Overlaps task #{other.task_id}.'})
    return issues

def generate_proposal(inputs, exclude_plan=None):
    config = PlanInput.model_validate(inputs)
    now = timezone.now()
    tz = timezone.get_current_timezone()
    qs = Task.objects.filter(status__in=ACTIVE).prefetch_related('dependencies')
    if config.task_ids is not None:
        missing = set(config.task_ids) - set(Task.objects.filter(pk__in=config.task_ids).values_list('pk', flat=True))
        if missing:
            raise ValidationError(f'Unknown task IDs: {sorted(missing)}')
        qs = qs.filter(pk__in=config.task_ids)
    tasks = sorted(qs, key=lambda t: (-priority_score(t, now), t.pk))
    commitments = list(approved_blocks(exclude_plan))
    occupied = [(b.start, b.end) for b in commitments] + [(b.start, b.end) for b in config.busy]
    blocks, unscheduled, done = [], [], {}
    committed_ids = {b.task_id for b in commitments}
    for b in commitments:
        done[b.task_id] = max(done.get(b.task_id, b.end), b.end)
    for task in Task.objects.filter(status='completed'):
        done[task.pk] = now
    used = {}
    for b in commitments:
        day = timezone.localdate(b.start)
        used[day] = used.get(day, 0) + (b.end - b.start).total_seconds() / 60
    pending = list(tasks)
    for _ in range(len(tasks) + 1):
        if not pending:
            break
        progressed = False
        for task in list(pending):
            deps = list(task.dependencies.all())
            if any(d.pk not in done for d in deps):
                continue
            pending.remove(task)
            progressed = True
            if task.pk in committed_ids:
                unscheduled.append({'task_id': task.pk, 'title': task.title, 'reason': 'Already has an approved commitment; preserved.'})
                continue
            if not task.estimated_minutes:
                unscheduled.append({'task_id': task.pk, 'title': task.title, 'reason': 'Add an estimated duration before scheduling.'})
                continue
            duration = timedelta(minutes=task.estimated_minutes)
            earliest = max([now] + [done[d.pk] for d in deps])
            found = False
            for offset in range((config.end_date - config.start_date).days + 1):
                day = config.start_date + timedelta(days=offset)
                if day.weekday() not in config.weekdays or used.get(day, 0) + task.estimated_minutes > config.daily_minutes:
                    continue
                start = max(datetime.combine(day, config.day_start, tz), earliest)
                limit = datetime.combine(day, config.day_end, tz)
                for os, oe in sorted(occupied):
                    if overlap(start, start + duration, os, oe):
                        start = oe.astimezone(tz)
                end = start + duration
                if end <= limit and (not task.deadline or end <= task.deadline):
                    blocks.append({'task_id': task.pk, 'title': task.title, 'start': start.isoformat(), 'end': end.isoformat(), 'minutes': task.estimated_minutes})
                    occupied.append((start, end))
                    done[task.pk] = end
                    used[day] = used.get(day, 0) + task.estimated_minutes
                    found = True
                    break
            if not found:
                unscheduled.append({'task_id': task.pk, 'title': task.title, 'reason': 'Cannot fit before deadline within the available hours/capacity.'})
        if not progressed:
            break
    unscheduled.extend({'task_id': t.pk, 'title': t.title, 'reason': 'Dependency is incomplete, unscheduled, or cyclic.'} for t in pending)
    return {'blocks': blocks, 'unscheduled': unscheduled, 'operations': [], 'warnings': [],
            'explanation': 'Ordered by importance and deadline pressure. Existing approved commitments are preserved. Tasks are scheduled in one uninterrupted block.'}

@transaction.atomic
def create_plan(inputs, source='user', previous=None):
    config = PlanInput.model_validate(inputs)
    target = previous if previous and previous.status == 'approved' else (replacement_target(previous) if previous else None)
    exclude = target.pk if target else None
    proposal = generate_proposal(config.model_dump(mode='json'), exclude)
    plan = Plan.objects.create(title=config.title, plan_type=config.plan_type, start_date=config.start_date,
        end_date=config.end_date, constraints=config.model_dump(mode='json'), proposal=proposal,
        previous=previous, revision=previous.revision + 1 if previous else 1)
    log('plan.proposed', plan.title, source, plan=plan)
    return plan

def validate_blocks(plan, raw_blocks):
    config = PlanInput.model_validate(plan.constraints)
    blocks = []
    used, seen = {}, set()
    target = replacement_target(plan)
    exclude = target.pk if target else None
    commitments = list(approved_blocks(exclude))
    for b in commitments:
        day = timezone.localdate(b.start)
        used[day] = used.get(day, 0) + (b.end - b.start).total_seconds() / 60
    occupied = [(b.start, b.end) for b in commitments] + [(b.start, b.end) for b in config.busy]
    ends = {b.task_id: b.end for b in commitments}
    tz = timezone.get_current_timezone()
    for raw in raw_blocks:
        block = ProposedBlock.model_validate({k: raw[k] for k in ['task_id', 'start', 'end']})
        task = Task.objects.filter(pk=block.task_id).first()
        if not task or task.status not in ACTIVE:
            raise ValidationError('A scheduled task was removed or is no longer active.')
        if config.task_ids is not None and task.pk not in config.task_ids:
            raise ValidationError('A block references a task outside the selected task IDs.')
        start, end = block.start.astimezone(tz), block.end.astimezone(tz)
        minutes = (end - start).total_seconds() / 60
        if block.task_id in seen or any(b.task_id == task.pk for b in commitments):
            raise ValidationError('A task cannot be scheduled twice.')
        if not task.estimated_minutes or minutes != task.estimated_minutes:
            raise ValidationError('Block duration must equal the current task estimate.')
        if start < timezone.now() or start.date() != end.date() or not config.start_date <= start.date() <= config.end_date:
            raise ValidationError('Block is in the past or outside the plan dates.')
        if start.weekday() not in config.weekdays or start.time() < config.day_start or end.time() > config.day_end:
            raise ValidationError('Block is outside permitted hours.')
        if task.deadline and end > task.deadline:
            raise ValidationError('Block misses the task deadline.')
        if any(overlap(start, end, a, b) for a, b in occupied):
            raise ValidationError('Schedule conflict detected.')
        used[start.date()] = used.get(start.date(), 0) + minutes
        if used[start.date()] > config.daily_minutes:
            raise ValidationError('Daily capacity exceeded.')
        occupied.append((start, end))
        seen.add(task.pk)
        ends[task.pk] = end
        blocks.append((task, start, end))
    for task, start, end in blocks:
        for dep in task.dependencies.all():
            if dep.status != 'completed' and (dep.pk not in ends or ends[dep.pk] > start):
                raise ValidationError(f'Dependency for {task.title} is not satisfied.')
    return blocks

@transaction.atomic
def approve_plan(pk, source='user'):
    plan = Plan.objects.select_for_update().get(pk=pk)
    if plan.status == 'approved':
        return plan
    if plan.status != 'draft':
        raise ValidationError('Only a draft can be approved.')
    target = replacement_target(plan)
    # Claim the draft with a conditional write, including on SQLite where row locking is limited.
    if not Plan.objects.filter(pk=pk, status='draft').update(status='approved'):
        raise ValidationError('This plan has already been processed.')
    if plan.proposal.get('operations'):
        from agent.operations import apply_operations
        apply_operations(plan.proposal['operations'])
    blocks = validate_blocks(plan, plan.proposal.get('blocks', [])) if plan.constraints else []
    if plan.previous_id:
        previous = Plan.objects.get(pk=plan.previous_id)
        if previous.status in ['draft', 'approved']:
            previous.status = 'superseded'
            previous.save(update_fields=['status'])
            previous.blocks.update(status='cancelled')
    if target:
        target.status = 'superseded'
        target.save(update_fields=['status'])
        target.blocks.update(status='cancelled')
    ScheduleBlock.objects.bulk_create([ScheduleBlock(task=t, plan=plan, start=s, end=e) for t, s, e in blocks])
    plan.status = 'approved'
    plan.approved_at = timezone.now()
    plan.save(update_fields=['status', 'approved_at'])
    log('plan.approved', plan.title, source, plan=plan)
    return plan

@transaction.atomic
def reject_plan(pk, source='user'):
    plan = Plan.objects.select_for_update().get(pk=pk)
    if plan.status != 'draft':
        raise ValidationError('Only drafts can be rejected.')
    plan.status = 'rejected'
    plan.save(update_fields=['status'])
    log('plan.rejected', plan.title, source, plan=plan)
    return plan

@transaction.atomic
def revise_plan(pk, data, source='user'):
    previous = Plan.objects.get(pk=pk)
    if previous.status not in ['draft', 'approved']:
        raise ValidationError('Revise an active draft or approved plan.')
    if previous.status == 'approved' and previous.proposal.get('operations'):
        raise ValidationError('These task changes were already applied. Edit the tasks directly or request a new proposal.')
    if 'proposal' in data:
        proposal = data['proposal']
        if not isinstance(proposal, dict) or set(proposal) - {'blocks', 'unscheduled', 'operations', 'warnings', 'explanation'}:
            raise ValidationError('Invalid proposal fields.')
        plan = Plan(title=previous.title, plan_type=previous.plan_type, start_date=previous.start_date,
            end_date=previous.end_date, constraints=previous.constraints, proposal=proposal,
            previous=previous, revision=previous.revision + 1)
        if previous.constraints:
            validate_blocks(plan, proposal.get('blocks', []))
            if proposal.get('operations'):
                raise ValidationError('Schedule revisions cannot add task operations.')
        else:
            from agent.operations import validate_operations
            validate_operations(proposal.get('operations', []))
            if proposal.get('blocks'):
                raise ValidationError('Task proposals cannot contain schedule blocks.')
        plan.save()
        log('plan.revised', plan.title, source, plan=plan)
    else:
        plan = create_plan({**previous.constraints, **data}, source, previous)
    if previous.status == 'draft':
        previous.status = 'superseded'
        previous.save(update_fields=['status'])
    return plan
