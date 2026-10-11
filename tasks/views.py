from django.db.models import Q
from rest_framework import viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Task, Goal, ActivityLog
from .serializers import TaskSerializer, GoalSerializer, ActivitySerializer
from . import services

def source(request):
    return 'user' if request.headers.get('X-Productivity-UI') == '1' else 'api'

class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    def get_queryset(self):
        qs = Task.objects.all()
        for key in ['status', 'priority', 'goal']:
            value = self.request.query_params.get(key)
            if value:
                if key == 'goal' and not value.isdigit():
                    return qs.none()
                qs = qs.filter(**{key: value})
        search = self.request.query_params.get('search', '')[:200]
        return qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
    def perform_create(self, serializer):
        serializer.instance = services.save_task(self.request.data, source=source(self.request))
    def perform_update(self, serializer):
        serializer.instance = services.save_task(self.request.data, serializer.instance, source(self.request))
    def perform_destroy(self, instance):
        services.delete_record(instance, source(self.request))
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        if set(request.data) - {'actual_minutes'}:
            raise serializers.ValidationError('Only actual_minutes is accepted here.')
        task = services.save_task({'status': 'completed', **{k: v for k, v in request.data.items() if k == 'actual_minutes'}}, self.get_object(), source(request))
        return Response(self.get_serializer(task).data)

class GoalViewSet(viewsets.ModelViewSet):
    queryset = Goal.objects.order_by('-created_at')
    serializer_class = GoalSerializer
    http_method_names = ['get', 'post', 'patch', 'delete', 'head', 'options']
    def perform_create(self, serializer):
        serializer.instance = services.save_goal(self.request.data, source=source(self.request))
    def perform_update(self, serializer):
        serializer.instance = services.save_goal(self.request.data, serializer.instance, source(self.request))
    def perform_destroy(self, instance):
        services.delete_record(instance, source(self.request))

class ActivityViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ActivityLog.objects.all()
    serializer_class = ActivitySerializer
