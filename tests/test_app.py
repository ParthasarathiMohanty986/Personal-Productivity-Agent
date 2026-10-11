import io
import json
from datetime import timedelta, datetime, time
from unittest.mock import patch, Mock
from django.test import TestCase
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient
from pydantic import ValidationError as PydanticError
from langchain_core.messages import AIMessage
from tasks.models import Task, Goal, ActivityLog
from tasks.services import save_task
from planner.models import Plan, ScheduleBlock
from planner.services import create_plan, approve_plan, reject_plan, revise_plan, priority_score, generate_proposal
from agent.schemas import Extraction, TaskProposal, Classification
from agent.operations import extraction_plan, proposal_plan
from agent import tools
from agent.workflow import build_workflow
from analytics.services import summary, trends

class Base(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.day = timezone.localdate() + timedelta(days=2)
        self.inputs = {'start_date': str(self.day), 'end_date': str(self.day), 'day_start': '09:00',
            'day_end': '17:00', 'daily_minutes': 120}
    def task(self, **kwargs):
        return save_task({'title': 'Learn Django', 'estimated_minutes': 60, **kwargs})

class TaskAPITests(Base):
    def test_crud_filters_and_delete_log(self):
        created = self.client.post('/api/tasks/', {'title': 'Read', 'priority': 'high'}, format='json')
        self.assertEqual(created.status_code, 201)
        pk = created.data['id']
        self.assertEqual(self.client.get(f'/api/tasks/{pk}/').status_code, 200)
        self.assertEqual(self.client.get('/api/tasks/?search=Read&priority=high').data['count'], 1)
        self.assertEqual(self.client.patch(f'/api/tasks/{pk}/', {'title': 'Write'}, format='json').status_code, 200)
        self.assertEqual(self.client.delete(f'/api/tasks/{pk}/').status_code, 204)
        self.assertTrue(ActivityLog.objects.filter(action='task.deleted').exists())
    def test_invalid_inputs(self):
        for data in [{'title': ''}, {'title': 'X', 'deadline': 'not-a-date'}, {'title': 'X', 'estimated_minutes': 0},
                     {'title': 'X', 'status': 'bogus'}, {'title': 'X', 'actual_minutes': -1}, {'title': 'X', 'unexpected': 1}]:
            self.assertEqual(self.client.post('/api/tasks/', data, format='json').status_code, 400, data)
    def test_completion_and_reopen(self):
        task = self.task()
        response = self.client.post(f'/api/tasks/{task.pk}/complete/', {'actual_minutes': 45}, format='json', HTTP_X_PRODUCTIVITY_UI='1')
        self.assertEqual(response.status_code, 200)
        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(task.actual_minutes, 45)
        self.assertEqual(ActivityLog.objects.first().source, 'user')
        completed_at = task.completed_at
        self.client.post(f'/api/tasks/{task.pk}/complete/', {}, format='json')
        task.refresh_from_db()
        self.assertEqual(task.completed_at, completed_at)
        self.client.patch(f'/api/tasks/{task.pk}/', {'status': 'pending'}, format='json')
        task.refresh_from_db()
        self.assertIsNone(task.completed_at)
    def test_goal_relationship(self):
        response = self.client.post('/api/goals/', {'title': 'Career'}, format='json')
        self.assertEqual(response.status_code, 201)
        pk = response.data['id']
        task = self.task(goal=pk)
        self.assertEqual(self.client.patch(f'/api/goals/{pk}/', {'description': 'Grow'}, format='json').status_code, 200)
        self.assertEqual(self.client.get(f'/api/goals/{pk}/').status_code, 200)
        self.client.delete(f'/api/goals/{pk}/')
        task.refresh_from_db()
        self.assertIsNone(task.goal)
    def test_dependency_cycles(self):
        first, second = self.task(), self.task()
        save_task({'dependencies': [first.pk]}, second)
        self.assertEqual(self.client.patch(f'/api/tasks/{first.pk}/', {'dependencies': [second.pk]}, format='json').status_code, 400)

class PlannerTests(Base):
    def test_priority(self):
        low = self.task(priority='low')
        urgent = self.task(priority='urgent', deadline=(timezone.now()-timedelta(days=1)).isoformat())
        self.assertGreater(priority_score(urgent), priority_score(low))
    def test_draft_approval_and_idempotency(self):
        self.task()
        response = self.client.post('/api/agent/plans/', self.inputs, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        plan = Plan.objects.get(pk=response.data['id'])
        self.assertEqual(ScheduleBlock.objects.count(), 0)
        for _ in range(2):
            response = self.client.post(f'/api/agent/plans/{plan.pk}/approve/', {}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(ScheduleBlock.objects.count(), 1)
        self.assertEqual(ActivityLog.objects.filter(action='plan.approved').count(), 1)
    def test_rejection_and_revision(self):
        self.task()
        first = create_plan(self.inputs)
        reject_plan(first.pk)
        self.assertEqual(ScheduleBlock.objects.count(), 0)
        with self.assertRaises(ValidationError):
            approve_plan(first.pk)
        second = create_plan(self.inputs)
        revised = revise_plan(second.pk, {'daily_minutes': 90})
        second.refresh_from_db()
        self.assertEqual(second.status, 'superseded')
        self.assertEqual(revised.revision, 2)
        approve_plan(revised.pk)
    def test_approved_revision_preserves_until_approved(self):
        self.task()
        first = create_plan(self.inputs)
        approve_plan(first.pk)
        revised = revise_plan(first.pk, {'day_start': '11:00'})
        self.assertEqual(ScheduleBlock.objects.filter(status='scheduled').count(), 1)
        first.refresh_from_db()
        self.assertEqual(first.status, 'approved')
        approve_plan(revised.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, 'superseded')
        self.assertEqual(ScheduleBlock.objects.filter(status='scheduled').count(), 1)
    def test_chained_revision_and_competing_draft(self):
        self.task()
        original = create_plan(self.inputs)
        approve_plan(original.pk)
        competing = revise_plan(original.pk, {'day_start':'12:00'})
        first = revise_plan(original.pk, {'day_start':'10:00'})
        second = revise_plan(first.pk, {'day_start':'11:00'})
        approve_plan(second.pk)
        self.assertEqual(ScheduleBlock.objects.filter(status='scheduled').count(), 1)
        with self.assertRaises(ValidationError): approve_plan(competing.pk)
    def test_capacity_deadlines_unknown_duration(self):
        self.task(estimated_minutes=150)
        self.task(estimated_minutes=None)
        self.task(deadline=(timezone.now()-timedelta(days=1)).isoformat())
        p = create_plan(self.inputs)
        self.assertEqual(len(p.proposal['blocks']), 0)
        self.assertEqual(len(p.proposal['unscheduled']), 3)
    def test_conflict_busy_and_capacity_with_commitments(self):
        self.task()
        first = create_plan(self.inputs)
        approve_plan(first.pk)
        second_task = self.task(title='Second')
        second = create_plan({**self.inputs, 'task_ids': [second_task.pk], 'daily_minutes': 60})
        self.assertEqual(len(second.proposal['blocks']), 0)
        third = create_plan({**self.inputs, 'task_ids': [second_task.pk]})
        self.assertEqual(datetime.fromisoformat(third.proposal['blocks'][0]['start']).hour, 10)
        third.proposal['blocks'][0]['start'] = first.proposal['blocks'][0]['start']
        third.proposal['blocks'][0]['end'] = first.proposal['blocks'][0]['end']
        third.save()
        with self.assertRaises(ValidationError): approve_plan(third.pk)
        third.refresh_from_db()
        self.assertEqual(third.status, 'draft')
    def test_busy_window(self):
        self.task()
        zone = timezone.get_current_timezone()
        busy = {'start': datetime.combine(self.day,time(9),zone).isoformat(), 'end': datetime.combine(self.day,time(11),zone).isoformat()}
        p = create_plan({**self.inputs,'busy':[busy]})
        self.assertEqual(datetime.fromisoformat(p.proposal['blocks'][0]['start']).hour, 11)
    def test_available_time_and_changed_commitment(self):
        from planner.services import available_time, schedule_issues
        self.assertEqual(available_time(self.inputs)['total_available_minutes'],120)
        task = self.task()
        plan = create_plan(self.inputs)
        approve_plan(plan.pk)
        self.assertEqual(available_time(self.inputs)['total_available_minutes'],60)
        save_task({'estimated_minutes':90},task)
        self.assertIn('estimate',schedule_issues()[0]['reason'])
    def test_dependencies_and_inactive(self):
        a = self.task(priority='low')
        b = self.task(priority='urgent', dependencies=[a.pk])
        self.task(status='completed')
        p = create_plan(self.inputs)
        self.assertEqual([x['task_id'] for x in p.proposal['blocks']], [a.pk,b.pk])
        approve_plan(p.pk)
    def test_stale_task_validation_atomic(self):
        t = self.task()
        p = create_plan(self.inputs)
        save_task({'estimated_minutes': 70},t)
        with self.assertRaises(ValidationError): approve_plan(p.pk)
        p.refresh_from_db()
        self.assertEqual(p.status, 'draft')
        self.assertEqual(ScheduleBlock.objects.count(), 0)
    def test_invalid_constraints_and_unknown_id(self):
        for payload in [{}, {**self.inputs,'daily_minutes':0}, {**self.inputs,'day_end':'08:00'}, {**self.inputs,'task_ids':[999]}]:
            self.assertEqual(self.client.post('/api/agent/plans/',payload,format='json').status_code,400)
    def test_edit_block_validation(self):
        self.task()
        p = create_plan(self.inputs)
        bad = {**p.proposal, 'blocks':[{'task_id':1,'start':'bad','end':'bad'}]}
        self.assertEqual(self.client.post(f'/api/agent/plans/{p.pk}/revise/', {'proposal':bad},format='json').status_code,400)

class AgentTests(Base):
    def test_structured_validation(self):
        for data in [{'title':'X','deadline':'2026-01-01T10:00:00'}, {'title':'X','estimated_minutes':-1}, {'title':'X','priority':'crazy'}]:
            with self.assertRaises(PydanticError): TaskProposal.model_validate(data)
    def test_tool_input_and_missing_record(self):
        with self.assertRaises(PydanticError): tools.get_task_details.invoke({'task_id':-1})
        for tool in [tools.get_task_details,tools.complete_task,tools.calculate_priority]:
            self.assertIn('error',tool.invoke({'task_id':999}))
        self.assertIn('error',tools.update_task.invoke({'task_id':999,'changes':{'title':'X'}}))
    def test_tool_write_is_only_proposal(self):
        result = tools.create_task.invoke({'task':{'title':'Review proposal'}})
        self.assertEqual(Task.objects.count(),0)
        approve_plan(result['plan_id'])
        self.assertEqual(Task.objects.count(),1)
        self.assertEqual(ActivityLog.objects.filter(action='task.created').first().source,'agent')
    def test_extraction_association_and_no_duplicate(self):
        p = extraction_plan({'goals':[{'title':'Learn'}],'tasks':[{'title':'Read','goal_index':0},{'title':'Practice','goal_index':0,'dependency_indices':[0]}]})
        approve_plan(p.pk)
        approve_plan(p.pk)
        self.assertEqual(Task.objects.count(),2)
        self.assertEqual(Goal.objects.count(),1)
        self.assertEqual(Task.objects.get(title='Practice').dependencies.get().title,'Read')
        with self.assertRaises(ValidationError): revise_plan(p.pk,{'proposal':p.proposal})
    def test_clarifications_do_not_persist_changes(self):
        p=extraction_plan({'tasks':[{'title':'Exercise'}],'clarifications':['Which dates?']})
        self.assertIsNone(p)
        self.assertEqual(Plan.objects.count(),0)
    def test_malformed_dependency_cycle(self):
        with self.assertRaises(ValidationError): extraction_plan({'tasks':[{'title':'A','dependency_indices':[1]},{'title':'B','dependency_indices':[0]}]})
    @patch.dict('os.environ',{'GEMINI_API_KEY':''})
    def test_no_key_does_not_break_crud_or_planner(self):
        for url in ['/api/agent/chat/','/api/agent/parse-tasks/']:
            response=self.client.post(url,{'message':'Help me'},format='json')
            self.assertEqual(response.status_code,503)
            self.assertIn('GEMINI_API_KEY',response.data['detail'])
        self.assertEqual(self.client.post('/api/tasks/',{'title':'Offline task'},format='json').status_code,201)
        self.assertEqual(self.client.post('/api/agent/plans/',self.inputs,format='json').status_code,201)
    def test_mock_extraction_workflow(self):
        model=Mock()
        model.with_structured_output.return_value.invoke.return_value=Extraction(tasks=[TaskProposal(title='Read')])
        result=build_workflow(model).invoke({'text':'Read','mode':'parse','messages':[]})
        self.assertEqual(len(result['plans']),1)
        self.assertEqual(Task.objects.count(),0)
    def test_tool_using_graph(self):
        self.task()
        model=Mock()
        model.with_structured_output.return_value.invoke.return_value=Classification(intent='assist')
        model.bind_tools.return_value.invoke.side_effect=[AIMessage(content='',tool_calls=[{'name':'get_productivity_summary','args':{},'id':'call-1'}]),AIMessage(content='You have one task.')]
        result=build_workflow(model).invoke({'text':'Summarize','mode':'chat','messages':[]})
        self.assertEqual(result['answer'],'You have one task.')
        self.assertEqual(result['calls'],1)
        self.assertEqual(result['events'][-1]['result']['total'],1)
    def test_bounded_tool_loop(self):
        model=Mock()
        model.with_structured_output.return_value.invoke.return_value=Classification(intent='assist')
        model.bind_tools.return_value.invoke.return_value=AIMessage(content='',tool_calls=[{'name':'list_tasks','args':{},'id':'loop'}])
        result=build_workflow(model).invoke({'text':'Loop','messages':[]},{'recursion_limit':20})
        self.assertEqual(result['error'],'tool_limit')
        self.assertEqual(result['calls'],4)
    @patch('agent.workflow.get_model')
    def test_provider_failure_is_sanitized(self,get_model):
        get_model.side_effect=RuntimeError('secret-api-key')
        response=self.client.post('/api/agent/chat/',{'message':'hello'},format='json')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('secret-api-key',str(response.data))

class AnalyticsAndFrontendTests(Base):
    def test_known_metrics(self):
        self.task(status='completed',estimated_minutes=60,actual_minutes=45)
        self.task(deadline=(timezone.now()-timedelta(days=1)).isoformat())
        self.task(status='cancelled')
        s=summary()
        self.assertEqual(s['completion_rate'],50)
        self.assertEqual(s['overdue'],1)
        self.assertEqual(s['estimated_vs_actual']['actual_minutes'],45)
        self.assertEqual(trends()['daily'][-1]['completed'],1)
    def test_postponements_and_missing_measurements(self):
        t=self.task(deadline=timezone.now().isoformat())
        save_task({'deadline':(timezone.now()+timedelta(days=2)).isoformat()},t)
        self.assertEqual(summary()['postponed_tasks'],1)
        self.assertIsNone(summary()['estimated_vs_actual'])
    def test_management_report_repeatable(self):
        for _ in range(2):
            out=io.StringIO();call_command('generate_productivity_report',stdout=out)
            self.assertEqual(json.loads(out.getvalue())['summary']['total'],0)
        self.assertEqual(ActivityLog.objects.count(),0)
    def test_frontend_and_csrf(self):
        client=APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/tasks/',{'title':'Denied'},format='json').status_code,403)
        response=client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Daylight')
        token=client.cookies['csrftoken'].value
        response=client.post('/api/tasks/',{'title':'From browser'},format='json',HTTP_X_CSRFTOKEN=token,HTTP_X_PRODUCTIVITY_UI='1')
        self.assertEqual(response.status_code,201)
        self.assertEqual(ActivityLog.objects.first().source,'user')
        self.assertEqual(client.get('/static/frontend/app.js').status_code,200)
    def test_all_read_routes(self):
        for url in ['/api/tasks/','/api/goals/','/api/agent/plans/','/api/analytics/summary/','/api/analytics/trends/','/api/activity/']:
            self.assertEqual(self.client.get(url).status_code,200,url)
        self.assertEqual(self.client.post('/api/analytics/report/',{},format='json').status_code,200)
