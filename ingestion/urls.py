from django.urls import path
from api.legacy_ingestion.views.ingest_view import IngestView
from api.legacy_ingestion.views.normalize_view import NormalizeView
from api.legacy_ingestion.views.sampling_view import SamplingView
from api.legacy_ingestion.views.graph_view import GraphView
from api.legacy_ingestion.views.pooling_view import PoolingView

urlpatterns = [
    path("ingest/", IngestView.as_view()),
    path("normalize/", NormalizeView.as_view()),
    path("sampling/", SamplingView.as_view()),
    path("graph/", GraphView.as_view()),
    path("pooling/", PoolingView.as_view()),
]