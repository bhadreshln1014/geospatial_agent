# --- START OF FILE models.py ---

from django.db import models
import uuid
import os
from werkzeug.utils import secure_filename

def get_upload_path(instance, filename):
    """Generate upload path: user_uploads/<thread_id>/<filename>"""
    safe_filename = secure_filename(filename)
    return os.path.join('user_uploads', str(instance.thread.id), safe_filename)

class AnalysisThread(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, default="New Analysis")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.id})"

class ThreadMessage(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(AnalysisThread, related_name='messages', on_delete=models.CASCADE)
    user_query = models.TextField(blank=True, null=True)
    agent_explanation = models.TextField(blank=True, null=True)
    agent_workflow_plan = models.JSONField(blank=True, null=True)
    user_edited_workflow_plan = models.JSONField(blank=True, null=True)
    execution_log = models.JSONField(blank=True, null=True)
    final_map_result = models.JSONField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['timestamp']

class UserDataLayer(models.Model):
    """Model to store user-uploaded spatial data layers."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(AnalysisThread, related_name='user_layers', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    data_type = models.CharField(max_length=50, choices=[('vector', 'Vector'), ('raster', 'Raster')])
    file = models.FileField(upload_to=get_upload_path)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.data_type}) - {self.thread.title}"

    class Meta:
        ordering = ['created_at']

class AnalysisROI(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.OneToOneField(AnalysisThread, related_name='roi', on_delete=models.CASCADE)
    geometry = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"ROI for {self.thread.title}"