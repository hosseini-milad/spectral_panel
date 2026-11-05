from django.urls import path
from . import views
from .registry import ACTIONS

app_name='api'
urlpatterns=[
    path('health/',views.HealthView.as_view(),name='health'),
    path('actions/',views.ActionCatalogView.as_view(),name='actions'),
    path('jobs/',views.JobListView.as_view(),name='jobs'),
    path('jobs/<uuid:job_id>/',views.JobDetailView.as_view(),name='job-detail'),
    path('jobs/<uuid:job_id>/logs/',views.JobLogsView.as_view(),name='job-logs'),
    path('jobs/<uuid:job_id>/cancel/',views.JobCancelView.as_view(),name='job-cancel'),
    path('artifacts/',views.ArtifactListView.as_view(),name='artifacts'),
    path('artifacts/file/',views.ArtifactFileView.as_view(),name='artifact-file'),
    path('days/',views.DaysView.as_view(),name='days'),
    path('days/<str:day>/chunks/',views.ChunksView.as_view(),name='chunks'),
]
urlpatterns += [path('actions/'+action+'/',views.action_view(action),name=action.replace('/','-')) for action in ACTIONS]
