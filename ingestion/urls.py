from django.urls import path
from .api.views.ingest_view import IngestView
from .api.views.normalize_view import NormalizeView
from .api.views.sampling_view import SamplingView
from .api.views.graph_view import GraphView
from .api.views.pooling_view import PoolingView

urlpatterns = [
    path("ingest/", IngestView.as_view()),
    path("normalize/", NormalizeView.as_view()),
    path("sampling/", SamplingView.as_view()),
    path("graph/", GraphView.as_view()),
    path("pooling/", PoolingView.as_view()),
]