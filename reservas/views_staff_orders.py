# reservas/views_staff_orders.py

from datetime import timedelta
from django.utils import timezone
from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse

from reservas.models import Mesa
from .models_orders import (
    Order,
    OrderStatus,
    Orden,       # POS (verde)
    OrdenItem,   # POS items
)

# ===============================
# CONFIG: minutos visibles en KDS
# ===============================

KDS_SERVED_VISIBLE_MINUTES = 10   # <<< AJÚSTALO AQUÍ


# ===============================
#   FILTRO PRINCIPAL DEL KDS
# ===============================
def kds_filtrar_ordenes_visibles(qs):
    """
    Mantiene el panel limpio:
      - IN_PREP, SUBMITTED, READY → SIEMPRE visibles
      - SERVED → solo visibles X minutos
    """
    ahora = timezone.now()
    cutoff = ahora - timedelta(minutes=KDS_SERVED_VISIBLE_MINUTES)

    return qs.filter(
        (
            # SIEMPRE VISIBLES
            OrderStatus.IN_PREP, 
            OrderStatus.SUBMITTED,
            OrderStatus.READY
        ) or
        # SERVED solo si es reciente
        (OrderStatus.SERVED and qs.filter(updated_at__gte=cutoff))
    )


# ===============================
#   Vista legacy de crear Order
# ===============================
@staff_member_required
def crear_orden_mesa(request):
    mesa_id = request.GET.get("mesa_id")
    mesa = get_object_or_404(Mesa, id=mesa_id)
    sucursal = mesa.sucursal

    # Buscar si existe una orden abierta en KDS
    orden = (
        Order.objects
        .filter(
            mesa=mesa,
            sucursal=sucursal,
            status__in=[
                OrderStatus.DRAFT,
                OrderStatus.SUBMITTED,
                OrderStatus.IN_PREP,
            ],
        )
        .order_by("-id")
        .first()
    )

    if not orden:
        orden = Order.objects.create(
            mesa=mesa,
            sucursal=sucursal,
            status=OrderStatus.DRAFT,
        )

    return render(request, "reservas/partials/orden_mesa.html", {
        "mesa": mesa,
        "orden": orden,
    })


# ===========================================
#   ACTUALIZAR STATUS DEL KDS + SINCRONIZAR POS
# ===========================================
@staff_member_required
@require_POST
def kds_update_status(request, order_id: int):
    order = get_object_or_404(
        Order.objects.select_related("mesa", "sucursal"),
        pk=order_id,
    )

    new_status = (request.POST.get("status") or "").strip()

    valid_statuses = {
        "SUBMITTED": OrderStatus.SUBMITTED,
        "IN_PREP":   OrderStatus.IN_PREP,
        "READY":     OrderStatus.READY,
        "SERVED":    OrderStatus.SERVED,
    }

    if new_status not in valid_statuses:
        return JsonResponse({"ok": False, "error": "Estado inválido."}, status=400)

    # 1) Actualizar estado del KDS
    order.status = valid_statuses[new_status]
    order.save(update_fields=["status"])

    updated_items = 0
    updated_ordenes = 0

    # 2) Si es SERVED → sincronizar POS
    if new_status == "SERVED" and order.mesa_id:

        # a) Items del POS de esa mesa → SERVIDO
        updated_items = OrdenItem.objects.filter(
            orden__mesa_id=order.mesa_id,
            cancelado=False,
        ).update(estado=OrdenItem.ESTADO_SERVIDO)

        # b) Órdenes POS → SERVIDA
        updated_ordenes = Orden.objects.filter(
            mesa_id=order.mesa_id,
        ).exclude(
            estado__in=["CERRADA", "CANCELADA"]
        ).update(estado="SERVIDA")

    return JsonResponse({
        "ok": True,
        "new_status": new_status,
        "mesa_id": order.mesa_id,
        "updated_items": updated_items,
        "updated_ordenes": updated_ordenes,
    })
