from django.contrib import admin
from django.urls import path, include
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.contrib.staticfiles.views import serve
from django.urls import re_path
from rest_framework.routers import DefaultRouter
from tasks.views import TaskViewSet, GoalViewSet, ActivityViewSet
from agent.views import PlanViewSet, chat, parse_tasks
from analytics.views import summary_view, trends_view, report_view
from frontend.views import index

router = DefaultRouter()
router.register('tasks', TaskViewSet, basename='task')
router.register('goals', GoalViewSet, basename='goal')
router.register('activity', ActivityViewSet, basename='activity')
router.register('agent/plans', PlanViewSet, basename='plan')
urlpatterns = [path('', index, name='dashboard'), path('admin/', admin.site.urls),
    path('api/agent/chat/', chat), path('api/agent/parse-tasks/', parse_tasks),
    path('api/analytics/summary/', summary_view), path('api/analytics/trends/', trends_view),
    path('api/analytics/report/', report_view), path('api/', include(router.urls)),
    # This project is local-only; serve static files even with safe DEBUG=False.
    re_path(r'^static/(?P<path>.*)$', serve, {'insecure': True})]
