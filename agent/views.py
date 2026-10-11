import uuid
from pydantic import ValidationError as PydanticError
from rest_framework import serializers, viewsets
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from langchain_core.messages import HumanMessage, AIMessage
from planner.models import Plan
from planner.serializers import PlanSerializer
from planner import services
from tasks.views import source
from .models import ConversationMessage
from .provider import ProviderUnavailable
from .workflow import run

class ChatInput(serializers.Serializer):
    message = serializers.CharField(max_length=8000, trim_whitespace=True)
    session_id = serializers.UUIDField(required=False)

def handle_chat(request, mode):
    serializer = ChatInput(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    session = data.get('session_id', uuid.uuid4())
    history = list(ConversationMessage.objects.filter(session_id=session).order_by('-created_at')[:10])[::-1]
    messages = [(HumanMessage if m.role == 'user' else AIMessage)(content=m.content) for m in history]
    try:
        result = run(data['message'], mode, messages)
    except ProviderUnavailable as exc:
        return Response({'detail': str(exc), 'code': 'ai_unavailable'}, status=503)
    ConversationMessage.objects.create(session_id=session, role='user', content=data['message'])
    ConversationMessage.objects.create(session_id=session, role='assistant', content=result.get('answer', ''),
        metadata={'plan_ids': result.get('plans', [])})
    return Response({'session_id': str(session), 'answer': result.get('answer', ''), 'extraction': result.get('extraction'),
        'events': result.get('events', []), 'plans': PlanSerializer(Plan.objects.filter(pk__in=result.get('plans', [])), many=True).data})

@api_view(['POST'])
def chat(request):
    return handle_chat(request, 'chat')

@api_view(['POST'])
def parse_tasks(request):
    return handle_chat(request, 'parse')

class PlanViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Plan.objects.order_by('-created_at')
    serializer_class = PlanSerializer
    def create(self, request):
        try:
            plan = services.create_plan(request.data, source(request))
        except PydanticError as exc:
            return Response({'detail': exc.errors(include_url=False, include_context=False)}, status=400)
        return Response(self.get_serializer(plan).data, status=201)
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        self.get_object()
        try:
            plan = services.approve_plan(pk, source(request))
        except PydanticError:
            return Response({'detail': 'The proposal is invalid. Revise it before approval.'}, status=400)
        return Response(self.get_serializer(plan).data)
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        self.get_object()
        return Response(self.get_serializer(services.reject_plan(pk, source(request))).data)
    @action(detail=True, methods=['post'])
    def revise(self, request, pk=None):
        self.get_object()
        try:
            plan = services.revise_plan(pk, request.data, source(request))
        except (PydanticError, KeyError, TypeError):
            return Response({'detail': 'Invalid revision. Check the proposal fields and timestamps.'}, status=400)
        return Response(self.get_serializer(plan).data, status=201)
