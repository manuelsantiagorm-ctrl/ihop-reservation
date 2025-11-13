# reservas/views_mesas_api.py
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required, user_passes_test

from .models import Mesa

def _staff_or_chain(user):
    return user.is_authenticated and (user.is_staff or user.is_superuser)

@login_required
@user_passes_test(_staff_or_chain)
@require_GET
def api_mesas_sucursal(request, sucursal_id: int):
    """
    GET /api/sucursal/<sucursal_id>/mesas/?min_cap=2 (opcional)
    Respuesta:
    {
      "mesas": [{"id":..., "numero":..., "nombre":..., "capacidad": ...}, ...]
    }
    """
    qs = Mesa.objects.filter(sucursal_id=sucursal_id)

    # filtro opcional de capacidad
    min_cap = request.GET.get("min_cap")
    if min_cap:
        try:
            qs = qs.filter(capacidad__gte=int(min_cap))
        except Exception:
            pass

    mesas = [{
        "id": m.id,
        "numero": getattr(m, "numero", None),
        "nombre": getattr(m, "nombre", None),
        "capacidad": getattr(m, "capacidad", None),
    } for m in qs.order_by("numero", "id")]

    return JsonResponse({"mesas": mesas})
