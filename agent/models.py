from django.db import models

class ConversationMessage(models.Model):
    session_id = models.UUIDField(db_index=True)
    role = models.CharField(max_length=10, choices=[('user', 'User'), ('assistant', 'Assistant')])
    content = models.TextField(max_length=12000)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
