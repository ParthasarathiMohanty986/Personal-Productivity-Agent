from rest_framework.decorators import api_view
from rest_framework.response import Response
from .services import summary, trends, report

@api_view(['GET'])
def summary_view(request):
    return Response(summary())

@api_view(['GET'])
def trends_view(request):
    return Response(trends())

@api_view(['POST'])
def report_view(request):
    return Response(report())
