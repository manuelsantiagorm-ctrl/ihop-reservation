# reservas/views_country.py
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from .models import Pais

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
