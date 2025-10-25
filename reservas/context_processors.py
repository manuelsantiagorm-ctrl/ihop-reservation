from django.conf import settings
from allauth.socialaccount.models import SocialApp
from .models import Pais


def google_maps(request):
    return {"GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", "")}


def social_flags(request):
    """Evita error DoesNotExist en signup.html si no hay app de Google configurada."""
    has_google = False

    # 1️⃣ Si está configurado por settings (via SOCIALACCOUNT_PROVIDERS)
    try:
        app_cfg = getattr(settings, "SOCIALACCOUNT_PROVIDERS", {}).get("google", {}).get("APP", {})
        if app_cfg.get("client_id") and app_cfg.get("secret"):
            has_google = True
    except Exception:
        pass

    # 2️⃣ O si existe una SocialApp en BD asociada al SITE_ID
    if not has_google:
        try:
            qs = SocialApp.objects.filter(provider="google")
            if getattr(settings, "SITE_ID", None):
                qs = qs.filter(sites__id=settings.SITE_ID)
            has_google = qs.exists()
        except Exception:
            pass

    return {"HAS_GOOGLE_LOGIN": has_google}

def countries_context(request):
    return {
        "all_countries": Pais.objects.order_by("nombre").only("id","nombre","iso2")
    }