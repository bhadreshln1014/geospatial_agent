from django.urls import path
from .views import PlannerView, ExecutorView

urlpatterns = [
    path('plan/', PlannerView.as_view(), name='planner_view'),
    path('execute/', ExecutorView.as_view(), name='executor_view'),
]