"""Minimal Django settings for project management commands."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "local-management-only"
DEBUG = False
ALLOWED_HOSTS = []

INSTALLED_APPS = [
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
