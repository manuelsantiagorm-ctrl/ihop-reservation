# ihop_system/urls.py
from django.contrib import admin
from django.urls import path, include
from django.views.i18n import JavaScriptCatalog
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    # ===============================
    # 🌐 PÚBLICO / RESERVAS
    # ===============================
    path("", include(("reservas.urls", "reservas"), namespace="reservas")),

    # ===============================
    # 👤 REGISTRO / LOGIN CLIENTES OTP
    # ===============================
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),

    # Alias para compatibilidad con rutas antiguas
    path("account/signup/", RedirectView.as_view(pattern_name="accounts:signup_start", permanent=False)),

    # ✅ Aliases EN ESPAÑOL a nivel raíz
    path("cuentas/registro/",  RedirectView.as_view(pattern_name="accounts:signup_start", permanent=False)),
    path("cuentas/verificar/", RedirectView.as_view(pattern_name="accounts:verify_email", permanent=False)),

    # ===============================
    # 🔐 LOGIN SOCIAL / STAFF (Allauth)
    # ===============================
    path("auth/", include("allauth.urls")),

    # 🔁 Redirecciones suaves para compatibilidad
    path("accounts/login/", RedirectView.as_view(url="/auth/login/", permanent=False)),
    path("accounts/logout/", RedirectView.as_view(url="/auth/logout/", permanent=False)),
    path("accounts/password/reset/", RedirectView.as_view(url="/auth/password/reset/", permanent=False)),

    # ✅ Nueva redirección: tras login → “Reservar”
    #    Si alguien entra a /auth/login/ y se autentica, lo manda a seleccionar_sucursal
    path(
        "after-login/",
        RedirectView.as_view(pattern_name="reservas:seleccionar_sucursal", permanent=False),
        name="after_login_redirect"
    ),

    # ===============================
    # 🔒 TWO-FACTOR AUTH (sin prefijo)
    # ===============================
    path("", include(("ihop_system.two_factor_urls_hotfix", "two_factor"), namespace="two_factor")),

    # ===============================
    # ⚙️ ADMIN DJANGO
    # ===============================
    path("admin/", admin.site.urls),

    # ===============================
    # 🌍 I18N / TRADUCCIONES JS
    # ===============================
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
]

# ===============================
# 🧩 DEBUG: MEDIA STATIC
# ===============================
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
