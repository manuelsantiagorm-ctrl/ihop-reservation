# ============================
# settings_restore.py — DEV local (sin OTP / sin TLS / sin Axes)
# ============================

from .settings import *  # importa todo lo común de tu proyecto

# ---- MODO DESARROLLO ----
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

# =========================
# BASE DE DATOS (ajusta según tus credenciales locales)
# =========================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "ihop_restore",
        "USER": "ihop_user",
        "PASSWORD": "BD",  # ⚠️ cambia por tu contraseña real
        "HOST": "127.0.0.1",
        "PORT": "5432",
    }
}

# =========================
# HTTPS / SEGURIDAD (desactivado en dev)
# =========================
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
CSRF_TRUSTED_ORIGINS = []  # no se necesita en HTTP local

# =========================
# EMAIL (a consola en local)
# =========================
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# =========================
# SENTRY OFF en DEV
# =========================
SENTRY_DSN = ""
# Si en settings base haces sentry_sdk.init(...), protégelo allí con:
# if SENTRY_DSN and not DEBUG: sentry_sdk.init(...)

# =========================
# CACHE SIMPLE
# =========================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "ihop-dev",
    }
}

# =========================
# MIDDLEWARE — limpieza en DEV
# =========================
try:
    MIDDLEWARE = [
        m for m in MIDDLEWARE
        if m not in (
            # Seguridad pesada que no necesitamos en local
            "axes.middleware.AxesMiddleware",
            "csp.middleware.CSPMiddleware",
            # OTP (Two-Factor) desactivado para desarrollo
            "django_otp.middleware.OTPMiddleware",
            "reservas.middleware.StaffOTPRequiredMiddleware",
        )
    ]
except NameError:
    pass

# =========================
# LOGIN Y REDIRECCIONES
# =========================
# Redirección simple tras login local
LOGIN_REDIRECT_URL = "/"
ACCOUNT_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL
TWO_FACTOR_LOGIN_REDIRECT_URL = LOGIN_REDIRECT_URL

# =========================
# ALLAUTH
# =========================
SITE_ID = 1
SOCIALACCOUNT_LOGIN_ON_GET = True

# =========================
# RECORDATORIO: Two-Factor desactivado
# =========================
# En este modo el login no pedirá OTP, ni generará códigos.
# Cuando vayas a producción, usa settings.py normal con OTP habilitado.



GOOGLE_TIMEZONE_API_KEY = "AIzaSyDM2X_Vy9wO544wVxn4ICKCmwvanzna5Z4"  # tu key; si se deja vacío no hace llamadas
TIMEZONE_HTTP_TIMEOUT = 4
