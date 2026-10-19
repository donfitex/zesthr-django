"""Production settings (default for wsgi.py).

Everything sensitive comes from real environment variables. If a critical value
is missing or unsafe, the app refuses to start instead of running insecurely.

Security hardening (HTTPS, cookies, headers, HSTS) is configured below and is
controlled by environment variables with safe defaults.
"""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .env import env, env_bool, env_list, require_env

# --- Core -----------------------------------------------------------------
SECRET_KEY = require_env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

# --- HTTPS and transport security ------------------------------------------
# Redirect all HTTP requests to HTTPS. Turn off only for a first smoke test
# before your certificate exists.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)

# Behind a reverse proxy / load balancer (Render, Railway, Nginx, ...) the app
# only sees plain HTTP. Set DJANGO_TRUST_PROXY_SSL_HEADER=True ONLY if your proxy
# sets X-Forwarded-Proto itself and strips any value sent by the client;
# otherwise visitors could spoof it, and without it you get a redirect loop.
if env_bool("DJANGO_TRUST_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# HSTS makes browsers refuse plain HTTP for the whole period, and is hard to
# undo. Leave at 0 until HTTPS works everywhere, then raise gradually:
# 3600 -> 86400 -> 2592000 -> 31536000 (one year).
SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "0"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_bool("DJANGO_HSTS_PRELOAD", False)
# Preload is a deliberate, near-permanent opt-in (browser preload lists), so the
# "preload not enabled" advisory is silenced instead of nudging anyone into it.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# --- Cookies ----------------------------------------------------------------
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# --- Browser protections ----------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# --- Database (PostgreSQL) ------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": require_env("DB_NAME"),
        "USER": require_env("DB_USER"),
        "PASSWORD": require_env("DB_PASSWORD"),
        "HOST": require_env("DB_HOST"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": int(env("DB_CONN_MAX_AGE", "60")),
    }
}

# --- Static files (served by WhiteNoise behind gunicorn) -------------------
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# --- Email ----------------------------------------------------------------
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")

# --- Logging: stdout only; the platform collects it ------------------------
LOGGING["root"]["level"] = env("DJANGO_LOG_LEVEL", "INFO")  # noqa: F405
LOGGING["formatters"]["simple"]["format"] = (  # noqa: F405
    "%(asctime)s %(levelname)s %(name)s: %(message)s"
)

# --- Startup validation ---------------------------------------------------
if DEBUG:
    raise ImproperlyConfigured("DJANGO_DEBUG must be False in production.")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("django-insecure") or "dev-only" in SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY is too short or looks insecure.")
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must list explicit host names (no '*').")
if any(not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("Every DJANGO_CSRF_TRUSTED_ORIGINS entry must start with https://.")
if SECURE_HSTS_PRELOAD and not (SECURE_HSTS_INCLUDE_SUBDOMAINS and SECURE_HSTS_SECONDS >= 31536000):
    raise ImproperlyConfigured(
        "HSTS preload requires DJANGO_HSTS_INCLUDE_SUBDOMAINS=True and DJANGO_HSTS_SECONDS >= 31536000."
    )
