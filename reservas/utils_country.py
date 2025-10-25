# reservas/utils_country.py
from typing import Optional
from .models import Pais

from django.utils.translation import gettext_lazy as _ais

from django.shortcuts import redirect
from django.contrib import messages

# reservas/views_country.py

def set_country(request):
    iso2 = (request.GET.get("iso2") or request.POST.get("iso2") or "").upper()
    try:
        pais = Pais.objects.get(iso2=iso2)
        request.session["country_iso2"] = pais.iso2
        messages.success(request, _("País cambiado a %(pais)s.") % {"pais": pais.nombre})
    except Pais.DoesNotExist:
        messages.error(request, _("País inválido."))
    # Regresa a la página anterior o home
    return redirect(request.META.get("HTTP_REFERER") or "reservas:home")

def _country_from_iso2(iso2: Optional[str]) -> Optional[Pais]:
    if not iso2:
        return None
    try:
        return Pais.objects.get(iso2=iso2.strip().upper())
    except Pais.DoesNotExist:
        return None

def get_effective_country(request, default_iso2="MX") -> Pais:
    # 1) Sesión (selector manual)
    c = _country_from_iso2(request.session.get("country_iso2"))
    if c:
        return c

    # 2) Encabezados de Cloudflare o AppEngine
    for header in ("HTTP_CF_IPCOUNTRY", "HTTP_X_APPENGINE_COUNTRY"):
        c = _country_from_iso2(request.META.get(header))
        if c:
            request.session["country_iso2"] = c.iso2
            return c

    # 3) GeoIP2 (opcional)
    try:
        from django.contrib.gis.geoip2 import GeoIP2
        ip = request.META.get("REMOTE_ADDR")
        if ip:
            data = GeoIP2().country(ip)
            c = _country_from_iso2((data or {}).get("country_code"))
            if c:
                request.session["country_iso2"] = c.iso2
                return c
    except Exception:
        pass

    # 4) Fallback (si todo falla)
    return Pais.objects.get(iso2=default_iso2)