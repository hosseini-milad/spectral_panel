"""Django settings for management commands and the standalone REST API."""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "local-management-only"
DEBUG = False
ALLOWED_HOSTS = [value.strip() for value in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if value.strip()]

INSTALLED_APPS = [
    "api",
    "rest_framework",
    "drf_spectacular",
    "drf_spectacular_sidecar",
    "django.contrib.staticfiles",
    "spectral_learning",
    "ingestion",
    "hierarchy"
]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django's management framework expects a relational database setting. The
# project data itself is stored in MongoDB through MongoEngine.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

from .mongo import connect_mongodb

connect_mongodb()

# REST orchestration is separate from the existing scientific/CLI applications.
ROOT_URLCONF = 'config.urls'
MIDDLEWARE = ['django.middleware.common.CommonMiddleware']
TIME_ZONE = 'UTC'
USE_TZ = True
STATIC_URL = '/static/'
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'UNAUTHENTICATED_USER': None,
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
}
SPECTACULAR_SETTINGS = {
    'TITLE': 'Spectral Project Operations API',
    'DESCRIPTION': 'Existing commands as queued actions. No authentication in this initial local API.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
    'SERVE_AUTHENTICATION': [],
    'SERVE_PERMISSIONS': ['rest_framework.permissions.AllowAny'],
    'SWAGGER_UI_DIST': 'SIDECAR',
    'SWAGGER_UI_FAVICON_HREF': 'SIDECAR',
    'REDOC_DIST': 'SIDECAR',
    'SWAGGER_UI_SETTINGS': {'deepLinking': True, 'persistAuthorization': False},
}
API_DB_TIMEOUT_SECONDS = 3
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': ['django.template.context_processors.request']},
}]
