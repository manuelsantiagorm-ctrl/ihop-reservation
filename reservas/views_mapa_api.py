from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET, require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404
from django.db import transaction

from .models import Sucursal, Mesa  # <- quitamos PosicionMesa
from .permissions import assert_user_can_manage_sucursal



# ============================================================
#  Listar mesas de una sucursal (para el mapa interactivo)
# ============================================================


@staff_member_required
@require_GET
def api_list_mesas(request, sucursal_id):
    # Usar el queryset seguro por usuario
    suc = get_object_or_404(Sucursal.objects.for_user(request.user), pk=sucursal_id)
    assert_user_can_manage_sucursal(request.user, suc)

    # ⬇️  Devolver también numero/pos_x/pos_y o el front no puede dibujar
    data = list(
        Mesa.objects.filter(sucursal=suc)
        .values("id", "numero", "zona", "pos_x", "pos_y", "capacidad", "estado", "bloqueada")
    )
    return JsonResponse({"mesas": data})

@staff_member_required
@require_POST
def api_guardar_posiciones(request, sucursal_id):
    suc = get_object_or_404(Sucursal.objects.for_user(request.user), pk=sucursal_id)
    assert_user_can_manage_sucursal(request.user, suc)
    # ... lógica de guardado ...
    return JsonResponse({"ok": True})

# ============================================================
#  Guardar posiciones (cuando el staff mueve mesas)
# ============================================================
@staff_member_required
@require_POST
@transaction.atomic
def api_guardar_posiciones(request, sucursal_id):
    """
    Guarda nuevas coordenadas de las mesas desde el mapa.
    Espera JSON como:
      {"mesas": [{"id": 1, "x": 50, "y": 120}, ...]}
    """
    suc = get_object_or_404(Sucursal.objects.for_user(request.user), pk=sucursal_id)
    assert_user_can_manage_sucursal(request.user, suc)

    try:
        import json
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    mesas_data = data.get("mesas", [])
    for mesa_info in mesas_data:
        mesa_id = mesa_info.get("id")
        x = mesa_info.get("x")
        y = mesa_info.get("y")
        if not mesa_id or x is None or y is None:
            continue

        Mesa.objects.filter(id=mesa_id, sucursal=suc).update(x=x, y=y)

    return JsonResponse({"ok": True})
