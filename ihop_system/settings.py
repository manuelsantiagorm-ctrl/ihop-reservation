"""
Django settings for ihop_system project.
"""

from pathlib import Path
from django.contrib.messages import constants as messages
from decouple import config
import os
from dotenv import load_dotenv
load_dotenv()


# =========================
# BASE
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "django-insecure-...SOLO_DEV..."
DEBUG = True  # <- cambia a False en producción
ALLOWED_HOSTS = ["127.0.0.1", "localhost"] if DEBUG else config("ALLOWED_HOSTS", default="").split(",")

# =========================
# APPS
# =========================
INSTALLED_APPS = [
    # Core Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",

    # Tu app principal
    "reservas.apps.ReservasConfig",   # ✅ Correcto — solo esta

    # Templates helpers
    "widget_tweaks",

    # Extras
    "django_extensions",
    "formtools",

    # Sites (para allauth)
    "django.contrib.sites",

    # Allauth
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",

    # Seguridad
    "csp",
    "axes",

    # 2FA / OTP
    "django_otp",
    "django_otp.plugins.otp_static",
    "django_otp.plugins.otp_totp",
    "two_factor",
]

SITE_ID = 1

# =========================
# MIDDLEWARE
# (LocaleMiddleware debe ir después de Session y antes de Common)
# =========================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "allauth.account.middleware.AccountMiddleware",

    # --- OTP y seguridad extra ---
    "django_otp.middleware.OTPMiddleware",                    # <- DESPUÉS de Authentication
    "reservas.middleware.StaffOTPRequiredMiddleware",
    "reservas.middleware.NoCacheForAuthPagesMiddleware",

    # Estos dos se desactivan automáticamente si DEBUG=True (abajo)
    "axes.middleware.AxesMiddleware",
    "csp.middleware.CSPMiddleware",

    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

ROOT_URLCONF = "ihop_system.urls"

# =========================
# TEMPLATES
# =========================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "ihop_system.wsgi.application"

# =========================
# BASE DE DATOS
# =========================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="ihop_db"),
        "USER": config("DB_USER", default="ihop_user"),
        "PASSWORD": config("DB_PASSWORD", default="bd"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "OPTIONS": {"sslmode": "disable"},
    }
}

# =========================
# PASSWORDS
# =========================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# =========================
# LOCALIZACIÓN / I18N
# =========================
USE_I18N = True
USE_TZ = True
TIME_ZONE = "America/Mexico_City"

LANGUAGE_CODE = "es-mx"
LANGUAGES = [
    ("es", "Español"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]

LANGUAGE_COOKIE_NAME = "django_language"
LANGUAGE_COOKIE_AGE = 60 * 60 * 24 * 365  # 1 año
LANGUAGE_COOKIE_SAMESITE = "Lax"
LANGUAGE_COOKIE_SECURE = not DEBUG

# =========================
# ESTÁTICOS / MEDIA
# =========================
STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# =========================
# LOGIN / LOGOUT
# (forzamos destino /admin/ para evitar loop en 2FA)
# =========================
# =========================
# LOGIN / LOGOUT (redirige a tu panel)
# =========================
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/staff/dashboard/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# Allauth mapea a lo anterior
ACCOUNT_AUTHENTICATED_LOGIN_REDIRECTS = True
ACCOUNT_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL
ACCOUNT_LOGOUT_REDIRECT_URL = LOGOUT_REDIRECT_URL

# Two-Factor usa el mismo destino post-login
TWO_FACTOR_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL



# =========================
# MENSAJES
# =========================
MESSAGE_TAGS = {
    messages.DEBUG: "secondary",
    messages.INFO: "info",
    messages.SUCCESS: "success",
    messages.WARNING: "warning",
    messages.ERROR: "danger",
}

# =========================
# ALLAUTH
# =========================
ACCOUNT_LOGIN_METHODS = {"email"}  # tu ajuste
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"

# =========================
# TWO-FACTOR / OTP
# =========================
TWO_FACTOR_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL
TWO_FACTOR_PATCH_ADMIN = True  # protege /admin con 2FA
# Recordatorio opcional de dispositivo (una semana):
TWO_FACTOR_REMEMBER_COOKIE_AGE = 60 * 60 * 24 * 7

# =========================
# EMAIL
# =========================
if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = "smtp.gmail.com"
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True
    EMAIL_HOST_USER = config("EMAIL_HOST_USER", default="")
    EMAIL_HOST_PASSWORD = config("EMAIL_HOST_PASSWORD", default="")
    DEFAULT_FROM_EMAIL = config("DEFAULT_FROM_EMAIL", default=EMAIL_HOST_USER)
    SERVER_EMAIL = DEFAULT_FROM_EMAIL

# =========================
# REGLAS DE RESERVAS
# =========================
RESERVA_DURACION_MIN_NORM = 90
RESERVA_DURACION_MIN_PICO = 105
HORAS_PICO = [(12, 15), (18, 21)]
RESERVAS_MAX_DIAS_ADELANTE = 30
RESERVA_LEAD_MIN = 15
RESERVA_ANTICIPACION_MIN = 20
RESERVA_ANTICIPACION_MIN_PICO = 30
CHECKIN_TOLERANCIA_MIN = 5
RESERVA_MIN_SEPARACION_MIN = 120
RESERVA_SEPARACION_POR_SUCURSAL = True
HORARIO_APERTURA = 8
HORARIO_CIERRE = 22

# ---- Reserva / asignación automática ----
BIG_CAP = 8          # mesa grande desde 8 pax
PROTECCION_BIG = 90  # min de protección para mesas grandes
WASTE_MAX = 3        # desperdicio máx durante protección
CAP_MAX = 12         # capacidad máxima de la cadena

# =========================
# SEGURIDAD
# =========================
SESSION_COOKIE_SAMESITE = "Lax"

# En PROD (DEBUG=False) forzamos HTTPS/HSTS; en DEV (DEBUG=True) lo desactivamos
SECURE_SSL_REDIRECT = not DEBUG
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

if DEBUG:
    # HSTS desactivado en DEV para evitar que el navegador fuerce https://
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
else:
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# --- CSP (django-csp >= 4) ---
_CSP_DIRECTIVES = {
    "default-src": ("'self'",),
    "script-src": ("'self'", "https://cdn.jsdelivr.net"),
    "style-src": ("'self'", "https://cdn.jsdelivr.net", "https://fonts.googleapis.com", "'unsafe-inline'"),
    "img-src": ("'self'", "data:", "https://maps.gstatic.com", "https://maps.googleapis.com"),
}
# En DEV: report-only; en PROD: bloqueo
if DEBUG:
    CONTENT_SECURITY_POLICY_REPORT_ONLY = {"DIRECTIVES": _CSP_DIRECTIVES}
else:
    CONTENT_SECURITY_POLICY = {"DIRECTIVES": _CSP_DIRECTIVES}

# --- Axes (anti-bruteforce) ---
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # horas

# =========================
# Sentry
# =========================
if not DEBUG and os.environ.get("SENTRY_DSN"):
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        integrations=[DjangoIntegration()],
        traces_sample_rate=0.1,
        send_default_pii=False,
    )

# =========================
# CACHE
# =========================
if DEBUG:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "ihop-dev",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/1"),
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "KEY_PREFIX": "ihop",
        }
    }

# =========================
# AJUSTES DINÁMICOS PARA DEV
# =========================
if DEBUG:
    # Quitamos middlewares pesados en local para evitar lentitud
    MIDDLEWARE = [
        m for m in MIDDLEWARE
        if m not in ("axes.middleware.AxesMiddleware", "csp.middleware.CSPMiddleware")
    ]
    # En DEV evita bucles http/https
    SECURE_SSL_REDIRECT = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False



GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")



TEMPLATES[0]["OPTIONS"]["context_processors"] += [
    "reservas.context_processors.google_maps",

]
