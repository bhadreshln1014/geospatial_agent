# --- START OF FILE urls.py ---

from django.urls import path, re_path
from .views import (
    UploadView,
    PlannerView,
    ExecutorView,
    ExecutorStreamView,
    ThreadListView,
    ThreadDetailView,
    ThreadMessagesView,
    ThreadLayersView,
    ServeMediaView
)

urlpatterns = [
    # Core API endpoints
    path('upload/', UploadView.as_view(), name='upload_view'),
    path('plan/', PlannerView.as_view(), name='planner_view'),
    path('execute/', ExecutorView.as_view(), name='executor_view'),
    path('execute/stream/', ExecutorStreamView.as_view(), name='executor_stream_view'),
    
    # Thread and data management endpoints
    path('threads/', ThreadListView.as_view(), name='thread_list'),
    path('threads/<uuid:thread_id>/', ThreadDetailView.as_view(), name='thread_detail'),
    path('threads/<uuid:thread_id>/messages/', ThreadMessagesView.as_view(), name='thread_messages'),
    path('threads/<uuid:thread_id>/layers/', ThreadLayersView.as_view(), name='thread_layers'),
    
    # Media serving (for development)
    re_path(r'^media/(?P<file_path>.*)$', ServeMediaView.as_view(), name='serve_media'),
]