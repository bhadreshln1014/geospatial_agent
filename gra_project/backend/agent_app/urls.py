from django.urls import path
from . import views

urlpatterns = [
    # Streaming endpoint for real-time CoT
    path('stream_query/', views.stream_query_agent, name='stream_query_agent'),
    # Endpoint to get available output files
    path('output_files/', views.get_output_files, name='get_output_files'),
]
