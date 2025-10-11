from django.contrib import admin
from django.urls import path, include
from django.views.i18n import JavaScriptCatalog
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("", include(("reservas.urls", "reservas"), namespace="reservas")),
    path("accounts/", include("allauth.urls")),

    # Usa el HOTFIX local con namespace two_factor
    path("", include(("ihop_system.two_factor_urls_hotfix", "two_factor"), namespace="two_factor")),

    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    path("", include("reservas.urls", namespace="reservas")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
