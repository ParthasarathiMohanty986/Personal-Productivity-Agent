from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from django.core.exceptions import ValidationError

class LocalSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        self.enforce_csrf(request)
        return super().authenticate(request)

def exception_handler(exc, context):
    from rest_framework.views import exception_handler as drf_exception_handler
    if isinstance(exc, ValidationError):
        return Response({'detail': exc.messages}, status=400)
    return drf_exception_handler(exc, context)
