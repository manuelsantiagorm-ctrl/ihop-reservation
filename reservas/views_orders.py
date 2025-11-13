# reservas/views_orders.py

from decimal import Decimal
import json

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.admin.views.decorators import staff_member_required
from django.http import (
    JsonResponse,
    HttpResponseForbidden,
    HttpResponseBadRequest,
    Http404,
)
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone

from .models import Mesa, Reserva, Sucursal
from .models_orders import (
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
)

# ---------------------------
# Helpers
# ---------------------------

def _is_staff(user):
    return user.is_authenticated and user.is_staff

# ---------------------------
# Panel de mesa (mesero)
# ---------------------------

@login_required
@user_passes_test(_is_staff)
def mesa_panel_order(request, mesa_id: int):
    """
    Abre (o crea) una orden ABIERTA para la mesa y muestra el panel del mesero.
    """
    mesa = get_object_or_404(Mesa.objects.select_related("sucursal"), pk=mesa_id)
    sucursal = mesa.sucursal

    # Orden abierta o la creamos (estado DRAFT por compatibilidad, pero usamos ABIERTA en OrderStatus)
    orden = (
        Order.objects.filter(mesa=mesa)
        .exclude(status=OrderStatus.CLOSED)
        .order_by("-id")
        .first()
    )
    if not orden:
        # intenta ligar a reserva activa si existe
        reserva = (
            Reserva.objects.filter(mesa=mesa, finalizada=False)
            .order_by("-id")
            .first()
        )
        orden = Order.objects.create(
            sucursal=sucursal,
            mesa=mesa,
            reserva=reserva,
            creado_por=request.user,
        )

    totals = orden.compute_totals_live() if hasattr(orden, "compute_totals_live") else {}
    ctx = {
        "mesa": mesa,
        "orden": orden,
        "totals": totals,
    }
    return render(request, "reservas/mesa_panel_order.html", ctx)

# ---------------------------
# API: agregar ítem rápido (libre)
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_POST
def add_item(request, order_id: int):
    """
    Agrega un ítem libre (nombre/precio/cantidad) a la orden.
    (Para ítems de catálogo usa los endpoints de views_ordenes.py)
    """
    orden = get_object_or_404(Order, pk=order_id)
    if orden.status == OrderStatus.CLOSED:
        return HttpResponseForbidden("Orden cerrada")

    nombre = (request.POST.get("nombre") or "").strip()
    try:
        precio = Decimal(request.POST.get("precio") or "0")
    except Exception:
        return JsonResponse({"ok": False, "error": "Precio inválido"})
    try:
        cantidad = int(request.POST.get("cantidad") or "1")
    except Exception:
        return JsonResponse({"ok": False, "error": "Cantidad inválida"})

    notas = (request.POST.get("notas") or "").strip()

    if not nombre or precio <= 0 or cantidad <= 0:
        return JsonResponse({"ok": False, "error": "Datos inválidos"})

    OrderItem.objects.create(
        order=orden,
        nombre=nombre,
        precio_unitario=precio,
        cantidad=cantidad,
        notas=notas,
    )

    totals = (
        orden.compute_totals_live() if hasattr(orden, "compute_totals_live") else {}
    )
    return JsonResponse({"ok": True, "totals": totals})

# ---------------------------
# Enviar orden a cocina (KDS)
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_POST
def submit_to_kitchen(request, order_id: int):
    orden = get_object_or_404(Order, pk=order_id)
    # Si tienes un método dedicado:
    if hasattr(orden, "submit_to_kitchen"):
        orden.submit_to_kitchen()
    else:
        orden.status = OrderStatus.SUBMITTED
        orden.submitted_at = timezone.now()
        orden.save(update_fields=["status", "submitted_at"])
    return JsonResponse({"ok": True, "status": orden.status})

# ---------------------------
# Cobrar y cerrar
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_POST
def cobrar_cerrar(request, order_id: int):
    orden = get_object_or_404(Order, pk=order_id)
    if orden.status == OrderStatus.CLOSED:
        return JsonResponse({"ok": False, "error": "Ya cerrada"})

    try:
        propina = Decimal(request.POST.get("propina") or "0")
    except Exception:
        propina = Decimal("0")

    metodo = request.POST.get("metodo") or PaymentMethod.CASH

    # Si tu modelo tiene helper close_and_free:
    if hasattr(orden, "close_and_free"):
        orden.propina = propina
        orden.close_and_free(user=request.user, payment_method=metodo)
    else:
        # Fallback simple
        orden.propina = propina
        orden.payment_method = metodo
        orden.status = OrderStatus.CLOSED
        orden.closed_at = timezone.now()
        orden.save(update_fields=["propina", "payment_method", "status", "closed_at"])

    return JsonResponse(
        {
            "ok": True,
            "redirect": reverse("reservas:ticket_order", args=[orden.id]),
        }
    )

# ---------------------------
# KDS (Cocina)
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_GET
def kds_list(request):
    """
    Lista órdenes activas en cocina (excluye DRAFT/CLOSED).
    """
    qs = (
        Order.objects.exclude(status=OrderStatus.DRAFT)
        .exclude(status=OrderStatus.CLOSED)
        .select_related("mesa", "sucursal", "reserva")
        .order_by("submitted_at", "id")
    )
    return render(request, "reservas/kds.html", {"orders": qs})


@login_required
@user_passes_test(_is_staff)
@require_POST
def kds_update_status(request, order_id: int):
    """
    Cambia estado en KDS: SUBMITTED -> IN_PREP -> READY -> SERVED.
    """
    orden = get_object_or_404(Order, pk=order_id)
    target = request.POST.get("status")

    allowed = {
        OrderStatus.SUBMITTED,
        OrderStatus.IN_PREP,
        OrderStatus.READY,
        OrderStatus.SERVED,
    }
    if target not in allowed:
        return JsonResponse({"ok": False, "error": "Estado inválido"})

    orden.status = target
    orden.save(update_fields=["status"])
    return JsonResponse({"ok": True, "status": orden.status})

# ---------------------------
# Ticket (imprimible)
# ---------------------------

@login_required
@user_passes_test(_is_staff)
def ticket_order(request, order_id: int):
    orden = get_object_or_404(Order, pk=order_id)

    if hasattr(orden, "compute_totals_live") and orden.status != OrderStatus.CLOSED:
        totals = orden.compute_totals_live()
    else:
        # Campos “persistidos” si ya está cerrada
        totals = {
            "subtotal_base": getattr(orden, "subtotal_base", None),
            "iva_total": getattr(orden, "iva_total", None),
            "total_bruto": getattr(orden, "total_bruto", None),
            "total_con_propina": getattr(orden, "total_con_propina", None),
        }

    return render(
        request,
        "reservas/ticket_thermal.html",
        {"orden": orden, "totals": totals},
    )

# JSON para el panel KDS (Cocina)
@login_required
@user_passes_test(_is_staff)
@require_GET
def kds_data(request):
    """
    Devuelve JSON con órdenes activas para el KDS.
    Incluye: SUBMITTED, IN_PREP, READY, SERVED (excluye DRAFT/CLOSED).
    """
    qs = (
        Order.objects.exclude(status=OrderStatus.DRAFT)
        .exclude(status=OrderStatus.CLOSED)
        .select_related("mesa", "sucursal")
        .prefetch_related("orderitem_set")
        .order_by("submitted_at", "id")
    )

    data = []
    for o in qs:
        items = []
        for it in o.orderitem_set.all():
            if getattr(it, "cancelado", False):
                continue
            items.append({
                "id": it.id,
                "nombre": it.nombre,
                "cantidad": it.cantidad,
                "notas": it.notas or "",
                "precio": str(it.precio_unitario),
                "importe": str(it.importe()),
            })

        data.append({
            "id": o.id,
            "mesa": (getattr(o.mesa, "numero", None) if o.mesa else None) or o.mesa_id or "",
            "sucursal": str(o.sucursal),
            "status": o.status,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else "",
            "items": items,
        })

    return JsonResponse({"orders": data})
