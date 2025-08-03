from django.db import models
import uuid

class AnalysisThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, default="New Analysis")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.id})"

class ThreadMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(AnalysisThread, related_name='messages', on_delete=models.CASCADE)
    
    # Message content
    user_query = models.TextField(blank=True, null=True)
    agent_explanation = models.TextField(blank=True, null=True)
    agent_workflow_plan = models.JSONField(blank=True, null=True)
    user_edited_workflow_plan = models.JSONField(blank=True, null=True)
    execution_log = models.JSONField(blank=True, null=True) # Store logs as a list of events
    final_map_result = models.JSONField(blank=True, null=True)
    
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']