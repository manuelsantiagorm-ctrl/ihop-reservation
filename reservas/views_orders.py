# reservas/views_orders.py
from decimal import Decimal
from datetime import timedelta
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
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.utils import timezone
from django.db.models import Q

# modelos “normales”
from .models import Mesa, Reserva, Sucursal

# modelos del POS
from .models_orders import (
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
)

# ===========================
# CONFIG / HELPERS
# ===========================

# minutos que dejamos las órdenes SERVED visibles en el KDS
KDS_SERVED_VISIBLE_MINUTES = 10


def _is_staff(user):
    """
    Filtro de acceso para vistas de staff/meseros/kitchen.
    Ajusta si luego metes ChainOwner, etc.
    """
    return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def _kds_visible_queryset(base_qs):
    """
    Mantiene el panel limpio:
      - SUBMITTED, IN_PREP, READY → siempre visibles
      - SERVED → solo los últimos X minutos
        (usando submitted_at, que ya tienes)
    """
    now = timezone.now()
    served_cut = now - timedelta(minutes=KDS_SERVED_VISIBLE_MINUTES)

    return base_qs.filter(
        Q(status__in=[
            OrderStatus.SUBMITTED,
            OrderStatus.IN_PREP,
            OrderStatus.READY,
        ])
        |
        (
            Q(status=OrderStatus.SERVED)
            & Q(submitted_at__isnull=False)
            & Q(submitted_at__gte=served_cut)
        )
    )


# ---------------------------
# Panel de mesa (mesero)
# ---------------------------
@login_required
@user_passes_test(_is_staff)
def mesa_panel_order(request, mesa_id: int):
    mesa = get_object_or_404(Mesa.objects.select_related("sucursal"), pk=mesa_id)
    sucursal = mesa.sucursal

    orden = (
        Order.objects.filter(mesa=mesa)
        .exclude(status=OrderStatus.CLOSED)
        .order_by("-id")
        .first()
    )
    if not orden:
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

    return render(
        request,
        "reservas/mesa_panel_order.html",
        {
            "mesa": mesa,
            "orden": orden,
            "totals": totals,
            "endpoint_item_update": reverse(
                "reservas:api_orden_pos_item_update",
                args=[orden.id]
            ),
        },
    )

# ---------------------------
# API: agregar ítem rápido
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_POST
def add_item(request, order_id: int):
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

    totals = orden.compute_totals_live() if hasattr(orden, "compute_totals_live") else {}

    return JsonResponse({"ok": True, "totals": totals})


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

    if hasattr(orden, "close_and_free"):
        orden.propina = propina
        orden.close_and_free(user=request.user, payment_method=metodo)
    else:
        orden.propina = propina
        orden.payment_method = metodo
        orden.status = OrderStatus.CLOSED
        orden.closed_at = timezone.now()
        orden.save(update_fields=["propina", "payment_method", "status", "closed_at"])

    return JsonResponse(
        {"ok": True, "redirect": reverse("reservas:ticket_order", args=[orden.id])}
    )


# ---------------------------
# KDS (Cocina) – HTML
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_GET
def kds_list(request):
    """
    Panel de cocina con filtros:
    - Mesa (?mesa=NUM)
    - Rango de tiempo (?rango=30|60|120|hoy)
    Además aplica la regla de SERVED últimos X minutos.
    """
    mesa_filtro = (request.GET.get("mesa") or "").strip()
    rango_filtro = (request.GET.get("rango") or "").strip()

    base_qs = (
        Order.objects
        .exclude(status=OrderStatus.DRAFT)
        .exclude(status=OrderStatus.CLOSED)
        .select_related("mesa", "sucursal", "reserva")
        .order_by("submitted_at", "id")
    )

    # Filtro por mesa
    if mesa_filtro:
        try:
            mesa_num = int(mesa_filtro)
            base_qs = base_qs.filter(mesa__numero=mesa_num)
        except ValueError:
            pass

    # Filtro por rango de tiempo
    now = timezone.now()
    if rango_filtro == "30":
        base_qs = base_qs.filter(submitted_at__gte=now - timedelta(minutes=30))
    elif rango_filtro == "60":
        base_qs = base_qs.filter(submitted_at__gte=now - timedelta(hours=1))
    elif rango_filtro == "120":
        base_qs = base_qs.filter(submitted_at__gte=now - timedelta(hours=2))
    elif rango_filtro == "hoy":
        base_qs = base_qs.filter(submitted_at__date=timezone.localdate())

    # Aplica regla de visibilidad
    qs = _kds_visible_queryset(base_qs)

    # Mesas para el combo
    mesa_ids = (
        Order.objects
        .exclude(status=OrderStatus.DRAFT)
        .exclude(status=OrderStatus.CLOSED)
        .values_list("mesa_id", flat=True)
        .distinct()
    )
    mesas_disponibles = (
        Mesa.objects
        .filter(id__in=mesa_ids)
        .order_by("numero")
    )

    context = {
        "orders": qs,
        "mesas_disponibles": mesas_disponibles,
        "mesa_filtro": mesa_filtro,
        "rango_filtro": rango_filtro,
        "minutes_visible": KDS_SERVED_VISIBLE_MINUTES,
    }
    return render(request, "reservas/kds.html", context)

# ---------------------------
# KDS JSON (para el JS)
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_GET
def kds_data(request):
    """
    JSON para el autorefresh del KDS.
    Acepta:
      - ?mesa=NUM
      - ?rango=30|60|120|hoy
    """
    mesa_filtro = (request.GET.get("mesa") or "").strip()
    rango_filtro = (request.GET.get("rango") or "").strip()

    base_qs = (
        Order.objects
        .exclude(status=OrderStatus.DRAFT)
        .exclude(status=OrderStatus.CLOSED)
        .select_related("mesa", "sucursal", "reserva")
        .prefetch_related("orderitem_set")
        .order_by("submitted_at", "id")
    )

    # Filtro por mesa
    if mesa_filtro:
        try:
            mesa_num = int(mesa_filtro)
            base_qs = base_qs.filter(mesa__numero=mesa_num)
        except ValueError:
            pass

    # Filtro por rango de tiempo
    now = timezone.now()
    if rango_filtro == "30":
        base_qs = base_qs.filter(submitted_at__gte=now - timedelta(minutes=30))
    elif rango_filtro == "60":
        base_qs = base_qs.filter(submitted_at__gte=now - timedelta(hours=1))
    elif rango_filtro == "120":
        base_qs = base_qs.filter(submitted_at__gte=now - timedelta(hours=2))
    elif rango_filtro == "hoy":
        base_qs = base_qs.filter(submitted_at__date=timezone.localdate())

    # 👇 ESTA LÍNEA FALTABA
    qs = _kds_visible_queryset(base_qs)

    data = []
    for o in qs:
        items = []
        for it in o.orderitem_set.all():
            if getattr(it, "cancelado", False):
                continue
            items.append(
                {
                    "id": it.id,
                    "nombre": it.nombre,
                    "cantidad": it.cantidad,
                    "notas": it.notas or "",  # 👈 aquí mandamos la nota
                    "precio": str(it.precio_unitario),
                    "importe": str(it.importe()),
                }
            )

        res = getattr(o, "reserva", None)
        if res:
            cliente = (
                getattr(res, "cliente_nombre", "")
                or str(getattr(res, "cliente", "") or "")
            )
            telefono = (
                getattr(res, "telefono", "")
                or getattr(getattr(res, "cliente", None), "telefono", "")
            )
            inicio = getattr(res, "local_inicio", None)
            fin = getattr(res, "local_fin", None)
            if inicio and fin:
                horario = f"{inicio.strftime('%H:%M')}–{fin.strftime('%H:%M')}"
            else:
                horario = ""
        else:
            cliente = ""
            telefono = ""
            horario = ""

        data.append(
            {
                "id": o.id,
                "mesa": getattr(o.mesa, "numero", "") or o.mesa_id,
                "sucursal": str(o.sucursal),
                "status": o.status,
                "submitted_at": o.submitted_at.isoformat() if o.submitted_at else "",
                "cliente": cliente,
                "telefono": telefono,
                "horario": horario,
                "items": items,
            }
        )

    return JsonResponse({"orders": data})


# ---------------------------
# KDS: actualizar estado simple
# ---------------------------

@login_required
@user_passes_test(_is_staff)
@require_POST
def kds_update_status(request, order_id: int):
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
# Ticket
# ---------------------------

@login_required
@user_passes_test(_is_staff)
def ticket_order(request, order_id: int):
    orden = get_object_or_404(Order, pk=order_id)

    if hasattr(orden, "compute_totals_live") and orden.status != OrderStatus.CLOSED:
        totals = orden.compute_totals_live()
    else:
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


# ---------------------------
# Enviar orden a cocina
# ---------------------------
@login_required
@user_passes_test(_is_staff)
@csrf_exempt
@require_POST
def submit_to_kitchen(request, order_id: int):
    orden = get_object_or_404(Order, pk=order_id)

    if orden.status == OrderStatus.CLOSED:
        return JsonResponse({"ok": False, "error": "La orden ya está cerrada."})

    if not orden.orderitem_set.filter(cancelado=False).exists():
        return JsonResponse({"ok": False, "error": "La orden está vacía."})

    # Solo marcamos SUBMITTED y submitted_at
    orden.status = OrderStatus.SUBMITTED
    if not orden.submitted_at:
        orden.submitted_at = timezone.now()
    orden.save(update_fields=["status", "submitted_at"])

    return JsonResponse({"ok": True, "status": orden.status})

# ==========================
#   API POS: actualizar NOTAS de un item
# ==========================
@login_required
@user_passes_test(_is_staff)
@require_POST
def api_orden_pos_item_update(request, order_id: int):
    """
    Actualiza las NOTAS de un platillo de una orden.
    Acepta:
      - form-data: item_id, notas
      - o JSON: {"item_id": ..., "notas": "..."}
      - también tolera "id" en lugar de "item_id"
    """
    item_id = None
    notas = ""

    ctype = (request.content_type or "").split(";")[0].strip()

    # JSON
    if ctype == "application/json":
        try:
            data = json.loads(request.body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            data = {}
        item_id = data.get("item_id") or data.get("id")
        notas = (data.get("notas") or "").strip()

    # form-data / x-www-form-urlencoded
    else:
        item_id = request.POST.get("item_id") or request.POST.get("id")
        notas = (request.POST.get("notas") or "").strip()

    if not item_id:
        return JsonResponse({"ok": False, "error": "Falta item_id."}, status=400)

    # Buscar item perteneciente a esa orden
    item = get_object_or_404(OrderItem, pk=item_id, order_id=order_id)

    # Guardar notas
    item.notas = notas
    item.save(update_fields=["notas"])

    return JsonResponse({"ok": True, "notas": item.notas})
