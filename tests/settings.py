"""
Django settings for running tests.

Based on pretix's testutils settings pattern.
"""

import atexit
import os
import tempfile

tmpdir = tempfile.TemporaryDirectory()
os.environ.setdefault("DATA_DIR", tmpdir.name)

from pretix.settings import *

LANGUAGE_CODE = "en"
DATA_DIR = tmpdir.name
LOG_DIR = os.path.join(DATA_DIR, "logs")
MEDIA_ROOT = os.path.join(DATA_DIR, "media")
SITE_URL = "http://example.com"

atexit.register(tmpdir.cleanup)

EMAIL_BACKEND = EMAIL_CUSTOM_SMTP_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

COMPRESS_ENABLED = COMPRESS_OFFLINE = False
COMPRESS_CACHE_BACKEND = "testcache"
STORAGES["staticfiles"]["BACKEND"] = "django.contrib.staticfiles.storage.StaticFilesStorage"  # type: ignore[name-defined]
PRETIX_INSTANCE_NAME = "pretix.eu"

COMPRESS_PRECOMPILERS_ORIGINAL = COMPRESS_PRECOMPILERS  # type: ignore[has-type,used-before-def]
COMPRESS_PRECOMPILERS = ()
TEMPLATES[0]["OPTIONS"]["loaders"] = (  # type: ignore[name-defined]
    ("django.template.loaders.cached.Loader", template_loaders),  # type: ignore[name-defined]
)

DEBUG = True
DEBUG_PROPAGATE_EXCEPTIONS = True

PRETIX_AUTH_BACKENDS = [
    "pretix.base.auth.NativeAuthBackend",
]

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Disable celery
CELERY_ALWAYS_EAGER = True
HAS_CELERY = False
CELERY_BROKER_URL = None
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = True

# Don't use redis
SESSION_ENGINE = "django.contrib.sessions.backends.db"
HAS_REDIS = False
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.dummy.DummyCache",
    }
}

# Set databases
DATABASE_REPLICA = "default"
DATABASES["default"]["CONN_MAX_AGE"] = 0  # type: ignore[name-defined]
DATABASES.pop("replica", None)  # type: ignore[name-defined]

MIDDLEWARE.insert(0, "pretix.testutils.middleware.DebugFlagMiddleware")  # type: ignore[name-defined]

if "pretix_enablebanking" not in INSTALLED_APPS:  # type: ignore[name-defined]
    INSTALLED_APPS.append("pretix_enablebanking")  # type: ignore[name-defined]
