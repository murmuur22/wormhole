import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.environ["WORMHOLE_SECRET_KEY"]
if len(SECRET_KEY) < 32:
    raise ValueError("WORMHOLE_SECRET_KEY must contain at least 32 characters")
STATE_DIR = Path(os.environ["WORMHOLE_STATE_DIR"])
ARCHIVE_ROOT = Path(os.environ["WORMHOLE_ARCHIVE_ROOT"])
ARCHIVE_ID = os.environ["WORMHOLE_ARCHIVE_ID"]
if not re.fullmatch("[0-9a-f]{32}", ARCHIVE_ID):
    raise ValueError("WORMHOLE_ARCHIVE_ID must be 32 lowercase hexadecimal characters")
for root in (STATE_DIR, ARCHIVE_ROOT):
    if not root.is_absolute() or root.is_symlink():
        raise ValueError("State and archive roots must be absolute real directories")
    if root == BASE_DIR or BASE_DIR in root.parents:
        raise ValueError("Mutable state must be outside application code")
    if not root.is_dir() or root.resolve() != root:
        raise ValueError("Operator must create real state/archive directories first")
SURFACE = os.environ.get("WORMHOLE_SURFACE", "portal")
if SURFACE not in {"portal", "admin"}:
    raise ValueError("Invalid surface")
ROOT_URLCONF = "wormhole.urls_" + SURFACE
DEBUG = False
STATIC_URL = "/static/"
ALLOWED_HOSTS = os.environ.get("WORMHOLE_HOSTS", "127.0.0.1,localhost").split(",")
if any(not h or "*" in h for h in ALLOWED_HOSTS):
    raise ValueError("Explicit hosts required")
ALLOWED_HOSTS = list(dict.fromkeys(["127.0.0.1", *ALLOWED_HOSTS]))
CSRF_TRUSTED_ORIGINS = list(
    filter(None, os.environ.get("WORMHOLE_CSRF_ORIGINS", "").split(","))
)
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "core",
]
MIDDLEWARE = [
    "core.middleware.Boundaries",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": STATE_DIR / "accounts.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.csrf",
            ]
        },
    }
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 14},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
]
SESSION_COOKIE_NAME = "wh_" + SURFACE
CSRF_COOKIE_NAME = "wh_csrf_" + SURFACE
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Strict"
SESSION_COOKIE_AGE = 8 * 3600
SESSION_COOKIE_SECURE = os.environ.get("WORMHOLE_SECURE_COOKIES", "1") == "1"
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
MAX_FILE_BYTES = 2 * 1024**3
CHUNK_BYTES = 512 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = CHUNK_BYTES + 65536
MAX_PENDING_PER_ACCOUNT = 4
MAX_PENDING_BYTES = 8 * 1024**3
MAX_PENDING_BYTES_PER_ACCOUNT = 2 * 1024**3
UPLOAD_TTL_SECONDS = 86400
