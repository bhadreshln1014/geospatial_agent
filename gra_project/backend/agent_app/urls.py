# --- START OF FILE urls.py ---

from django.urls import path, re_path

from .geoserver_utils import wms_proxy
from .views import UploadView, PlannerView, ExecutorView, ExecutorStreamView, ThreadListView, ThreadDetailView, ThreadMessagesView, ThreadLayersView, ConvertGpkgView

urlpatterns = [
    # Core API endpoints
    path('upload/', UploadView.as_view(), name='upload_view'),
    path('plan/', PlannerView.as_view(), name='planner_view'),
    path('execute/', ExecutorView.as_view(), name='executor_view'),
    path('execute/stream/', ExecutorStreamView.as_view(), name='executor_stream_view'),
    
    # Thread and data management endpoints
    path('threads/', ThreadListView.as_view(), name='thread_list'),
    path('threads/<str:thread_id>/messages/', ThreadMessagesView.as_view(), name='thread_messages'),
    path('threads/<str:thread_id>/layers/', ThreadLayersView.as_view(), name='thread_layers'),
    path('wms-proxy/', wms_proxy, name='wms-proxy'),

]