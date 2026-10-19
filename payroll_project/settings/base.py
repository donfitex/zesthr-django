"""Settings shared by every environment.

This module must stay safe: no secrets, no DEBUG=True, no host wildcards.
SECRET_KEY, DEBUG, ALLOWED_HOSTS and DATABASES are set per environment.
"""
from pathlib import Path

from dotenv import load_dotenv

from .env import env, env_bool

# settings/base.py -> settings -> payroll_project -> project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Reads <project root>/.env if it exists. override=False: real environment
# variables (e.g. set by the hosting platform) always win over the file.
load_dotenv(BASE_DIR / ".env", override=False)

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.ForcePasswordChangeMiddleware",
]

ROOT_URLCONF = "payroll_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

WSGI_APPLICATION = "payroll_project.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# Kept at the previous hardcoded value so behaviour does not change.
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Kolkata")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"  # target of `collectstatic` (production)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Sessions: sliding idle timeout (each request renews it) -----------------
SESSION_IDLE_MINUTES = int(env("DJANGO_SESSION_IDLE_MINUTES", "60"))
SESSION_COOKIE_AGE = SESSION_IDLE_MINUTES * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

# --- Password reset and sign-in protection ---------------------------------
PASSWORD_RESET_TIMEOUT = int(env("DJANGO_PASSWORD_RESET_MINUTES", "60")) * 60  # reset links expire
LOGIN_MAX_FAILURES = int(env("DJANGO_LOGIN_MAX_FAILURES", "5"))
LOGIN_FAILURE_WINDOW_MINUTES = int(env("DJANGO_LOGIN_FAILURE_WINDOW_MINUTES", "15"))
# Trust X-Forwarded-For for the audit log's IP address ONLY if your proxy overwrites it.
TRUST_X_FORWARDED_FOR = env_bool("DJANGO_TRUST_X_FORWARDED_FOR", False)
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", "HROS <noreply@localhost>")

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {"format": "%(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "simple"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
