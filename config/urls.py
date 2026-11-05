from pathlib import PurePosixPath
from django.contrib.staticfiles.views import serve
from django.http import Http404
from django.urls import include,path
from django.views.decorators.http import require_GET
from django.views.generic import RedirectView
from drf_spectacular.views import SpectacularAPIView,SpectacularSwaggerView,SpectacularRedocView


@require_GET
def swagger_asset(request,path):
    # Local Swagger assets work with DEBUG=False, without a CDN or collectstatic.
    if '..' in PurePosixPath(path).parts:raise Http404()
    return serve(request,'drf_spectacular_sidecar/'+path,insecure=True)


urlpatterns=[
    path('',RedirectView.as_view(url='/swagger/',permanent=False)),
    path('api/v1/',include('api.urls')),
    path('api/schema/',SpectacularAPIView.as_view(),name='schema'),
    path('swagger/',SpectacularSwaggerView.as_view(url_name='schema'),name='swagger'),
    path('redoc/',SpectacularRedocView.as_view(url_name='schema'),name='redoc'),
    path('static/drf_spectacular_sidecar/<path:path>',swagger_asset),
]
