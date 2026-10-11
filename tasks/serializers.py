from rest_framework import serializers
from .models import Task, Goal, ActivityLog

class StrictModelSerializer(serializers.ModelSerializer):
    def to_internal_value(self, data):
        unknown = set(data) - {k for k, v in self.fields.items() if not v.read_only}
        if unknown:
            raise serializers.ValidationError({k: 'Unknown or read-only field.' for k in unknown})
        return super().to_internal_value(data)

class TaskSerializer(StrictModelSerializer):
    class Meta:
        model = Task
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at', 'completed_at']

    def validate(self, attrs):
        deps = attrs.get('dependencies', [])
        if self.instance:
            seen = set()
            def reaches(task):
                if task.pk == self.instance.pk:
                    return True
                if task.pk in seen:
                    return False
                seen.add(task.pk)
                return any(reaches(d) for d in task.dependencies.all())
            if any(reaches(d) for d in deps):
                raise serializers.ValidationError({'dependencies': 'Dependencies must not form a cycle.'})
        return attrs

class GoalSerializer(StrictModelSerializer):
    class Meta:
        model = Goal
        fields = '__all__'
        read_only_fields = ['created_at', 'updated_at']

class ActivitySerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields = '__all__'
