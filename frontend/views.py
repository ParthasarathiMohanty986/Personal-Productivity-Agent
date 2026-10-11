import os
from django.conf import settings
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

@ensure_csrf_cookie
def index(request):
    return render(request, 'frontend/index.html', {'ai_configured': bool(os.getenv('GEMINI_API_KEY')), 'local_timezone': settings.TIME_ZONE})
