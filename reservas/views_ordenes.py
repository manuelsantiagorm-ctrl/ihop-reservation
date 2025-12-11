# reservas/views_ordenes.py
import json
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string

from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from decimal import Decimal
from django.template.loader import render_to_string


# Modelos propios
from .models import Mesa, Reserva

from .models_orders import (
    Orden,
    OrdenItem,
    Order,
    OrderItem as LegacyOrderItem,
    OrderStatus,
    PaymentMethod,
)
from .models_menu import CatalogItem


# IVA usado para el cálculo en el modal POS
IVA_RATE = Decimal("0.16")   # 16%
IVA_DEFAULT = IVA_RATE       # alias por compatibilidad


def _r2(x: Decimal) -> Decimal:
    """Redondeo a 2 decimales, modo ticket."""
    return (x or Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _is_staff(user):
    return user.is_authenticated and user.is_staff


# === Config ===
# === Config ===
TEMPLATE_ORDER_MODAL = "reservas/partials/orden_modal.html"



# =========================================================
# Helpers
# =========================================================
def _get_or_create_open_order(mesa: Mesa) -> Orden:
    """
    Devuelve la orden ABIERTA más reciente de la mesa;
    si no existe, la crea.
    """
    orden = (
        Orden.objects
        .filter(mesa=mesa, estado="ABIERTA")
        .order_by("-creada_en")
        .first()
    )
    if not orden:
        orden = Orden.objects.create(
            sucursal=mesa.sucursal,
            mesa=mesa,
            estado="ABIERTA",
        )
    return orden


def _render_modal(orden: Orden) -> str:
    """
    Renderiza el HTML del modal de la orden (lado derecho del POS).
    Los precios del menú ya incluyen IVA, así que:
      - sumamos total_bruto = suma de renglones
      - base = total_bruto / (1 + IVA_RATE)
      - iva  = total_bruto - base
      - total = total_bruto
    """
    items_qs = orden.items.filter(cancelado=False).order_by("id")

    items = []
    total_bruto = Decimal("0.00")

    for it in items_qs:
        precio = it.precio_unit or Decimal("0.00")
        cantidad = it.cantidad or 0
        importe = (precio * cantidad).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total_bruto += importe

        items.append(
            {
                "id": it.id,
                "nombre": it.nombre,
                "cantidad": cantidad,
                "precio": f"${precio:.2f}",
                "importe": f"${importe:.2f}",
                "notas": it.notas or "",
                "estado": it.estado,
            }
        )

    # === mismo criterio que el ticket ===
    uno_mas_iva = Decimal("1.00") + IVA_RATE
    base = (total_bruto / uno_mas_iva).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    iva = (total_bruto - base).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total = total_bruto  # lo que ve el cliente / ticket

    ctx = {
        "orden": orden,
        "mesa": orden.mesa,
        "sucursal": orden.sucursal,
        "ahora_local": timezone.localtime(),
        "items": items,
        "subtotal": base,      # <--- base sin IVA
        "impuestos": iva,
        "total": total,        # <--- total con IVA (coincide con ticket)
        "endpoint_buscar": reverse("reservas:menu_api_buscar"),
        "endpoint_add": reverse("reservas:api_orden_crear"),
        "endpoint_item_update": reverse("reservas:api_orden_item_update"),
        "endpoint_item_split": reverse("reservas:api_orden_item_split"),
        "endpoint_item_remove": reverse("reservas:api_orden_item_remove"),
    }
    return render_to_string(TEMPLATE_ORDER_MODAL, ctx)

# =======================================================================
#                     ORDEN MESA NUEVA (POS)
# =======================================================================

def orden_mesa_nueva(request):
    """
    Abre el modal POS para una mesa.

    - Si hay una Orden ABIERTA / EN_COCINA / SERVIDA -> la reutiliza.
    - Si solo hay órdenes CERRADA / CANCELADA -> crea una nueva limpia.
    - Intenta ligar la Orden con la última Reserva de esa mesa (si existe).
    """
    mesa_id = request.GET.get("mesa_id")
    mesa = get_object_or_404(Mesa, id=mesa_id)
    sucursal = mesa.sucursal

    # 🔗 Buscar la última reserva asociada a esa mesa (aunque no tenga 'finalizada')
    # Tomamos la más reciente por ID; si luego quieres filtrar por estado, lo afinamos.
    reserva = (
        Reserva.objects
        .filter(mesa=mesa)
        .order_by("-id")
        .first()
    )

    # 🔍 Buscar orden POS abierta/activa de esa mesa
    orden = (
        Orden.objects
        .filter(
            mesa=mesa,
            sucursal=sucursal,
            estado__in=[
                Orden.ESTADO_ABIERTA,
                Orden.ESTADO_EN_COCINA,
                Orden.ESTADO_SERVIDA,
            ],
        )
        .order_by("-creada_en")
        .first()
    )

    # Si NO hay orden abierta -> crear una NUEVA vacía
    if not orden:
        orden = Orden.objects.create(
            mesa=mesa,
            sucursal=sucursal,
            reserva=reserva,            # la ligamos desde el inicio
            estado=Orden.ESTADO_ABIERTA,
        )
    else:
        # Si sí hay orden pero aún no tiene reserva ligada y encontramos una, la pegamos
        if reserva and orden.reserva_id is None:
            orden.reserva = reserva
            orden.save(update_fields=["reserva"])

    # Usamos SIEMPRE el mismo render que el resto del POS
    html = _render_modal(orden)

    # Nuestro JS soporta dos modos:
    # - Si viene JSON {ok, html} -> usa html
    # - Si viene HTML directo -> lo mete tal cual
    # Aquí devolvemos JSON para ser consistentes.
    return JsonResponse({"ok": True, "html": html})


# =======================================================================
#                    AUTOCOMPLETE MENÚ / CRUD ITEMS
# =======================================================================

@staff_member_required
@require_GET
def api_menu_buscar(request):
    """
    Autocomplete para el buscador del modal.
    Responde: {"results": [{"codigo","nombre","precio"}, ...]}
    """
    q = (request.GET.get("q") or "").strip()

    qs = CatalogItem.objects.filter(activo=True)
    if q:
        if hasattr(CatalogItem, "codigo"):
            qs = qs.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))
        else:
            qs = qs.filter(nombre__icontains=q)

    qs = qs.select_related("categoria").order_by(
        "categoria__orden", "nombre"
    )[:25]

    results = []
    for obj in qs:
        codigo = getattr(obj, "codigo", None) or obj.nombre
        precio = getattr(obj, "precio", None)
        if precio is None:
            precio = getattr(obj, "price", 0)
        results.append(
            {
                "codigo": str(codigo),
                "nombre": str(obj.nombre),
                "precio": float(precio or 0),
            }
        )

    return JsonResponse({"results": results})


@staff_member_required
@require_POST
def api_orden_crear(request):
    """
    Agrega un ítem del catálogo a una orden EXISTENTE.
    Siempre usa el precio del menú.

    Body JSON: {orden_id, codigo, cantidad, notas}
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido."}, status=400)

    orden_id = int(data.get("orden_id") or 0)
    codigo = (data.get("codigo") or "").strip()
    cantidad = max(1, int(data.get("cantidad") or 1))
    notas = (data.get("notas") or "").strip()

    if not orden_id or not codigo:
        return JsonResponse(
            {"ok": False, "error": "Faltan datos requeridos."}, status=400
        )

    orden = get_object_or_404(Orden, pk=orden_id)

    # Buscar en catálogo: soporta 'codigo' o 'nombre' como código
    if hasattr(CatalogItem, "codigo"):
        item = CatalogItem.objects.filter(
            activo=True, codigo__iexact=codigo
        ).first()
        if not item:
            item = CatalogItem.objects.filter(
                activo=True, nombre__iexact=codigo
            ).first()
    else:
        item = CatalogItem.objects.filter(
            activo=True, nombre__iexact=codigo
        ).first()

    if not item:
        return JsonResponse(
            {"ok": False, "error": "El código no existe en el Menú."}, status=400
        )

    # Tomar SIEMPRE el precio del menú
    precio = getattr(item, "precio", None)
    if precio is None:
        precio = getattr(item, "price", None)
    if precio is None:
        return JsonResponse(
            {"ok": False, "error": "El ítem de menú no tiene precio."}, status=500
        )

    categoria_nombre = ""
    cat = getattr(item, "categoria", None)
    if cat is not None:
        categoria_nombre = (
            getattr(cat, "nombre", "") or getattr(cat, "name", "") or ""
        )

    OrdenItem.objects.create(
        orden=orden,
        catalog_item=None,  # si no usas FK directa, déjalo en None
        codigo=(getattr(item, "codigo", None) or item.nombre),
        nombre=getattr(item, "nombre", "") or getattr(item, "name", ""),
        categoria_nombre=categoria_nombre,
        precio_unit=precio,
        cantidad=cantidad,
        notas=notas,
    )

    html = _render_modal(orden)
    return JsonResponse({"ok": True, "html": html})


@staff_member_required
@require_POST
def api_orden_item_update(request):
    """
    Actualiza notas y/o cantidad de un OrdenItem.
    Body: { item_id, orden_id, notas, cantidad }
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido."}, status=400)

    item_id = int(data.get("item_id") or 0)
    orden_id = int(data.get("orden_id") or 0)
    notas = (data.get("notas") or "").strip()
    cantidad = int(data.get("cantidad") or 0)

    if not item_id or not orden_id:
        return JsonResponse({"ok": False, "error": "Faltan IDs."}, status=400)

    item = get_object_or_404(OrdenItem, pk=item_id, orden_id=orden_id)
    if cantidad <= 0:
        return JsonResponse(
            {"ok": False, "error": "Cantidad inválida."}, status=400
        )

    item.cantidad = cantidad
    item.notas = notas
    item.save(update_fields=["cantidad", "notas"])

    orden = item.orden
    html = _render_modal(orden)
    return JsonResponse({"ok": True, "html": html})


@staff_member_required
@require_POST
def api_orden_item_split(request):
    """
    Divide un renglón en dos:
    - reduce la cantidad del original
    - crea un nuevo renglón con cantidad_nueva y notas_nuevas

    Body: { item_id, orden_id, cantidad_nueva, notas_nuevas }
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido."}, status=400)

    item_id = int(data.get("item_id") or 0)
    orden_id = int(data.get("orden_id") or 0)
    cantidad_nueva = int(data.get("cantidad_nueva") or 0)
    notas_nuevas = (data.get("notas_nuevas") or "").strip()

    if not item_id or not orden_id or cantidad_nueva <= 0:
        return JsonResponse(
            {"ok": False, "error": "Datos incompletos."}, status=400
        )

    item = get_object_or_404(OrdenItem, pk=item_id, orden_id=orden_id)
    if cantidad_nueva >= item.cantidad:
        return JsonResponse(
            {
                "ok": False,
                "error": "La cantidad a dividir debe ser menor a la actual.",
            },
            status=400,
        )

    # 1) reduce el original
    restante = item.cantidad - cantidad_nueva
    item.cantidad = restante
    item.save(update_fields=["cantidad"])

    # 2) crea el nuevo con mismo producto / precio
    OrdenItem.objects.create(
        orden=item.orden,
        catalog_item=item.catalog_item,
        codigo=item.codigo,
        nombre=item.nombre,
        categoria_nombre=item.categoria_nombre,
        precio_unit=item.precio_unit,
        cantidad=cantidad_nueva,
        notas=notas_nuevas,
    )

    html = _render_modal(item.orden)
    return JsonResponse({"ok": True, "html": html})


@login_required
@user_passes_test(_is_staff)
@require_GET
def api_orden_detalle(request, orden_id: int):
    orden = get_object_or_404(Orden, pk=orden_id)

    # Pendientes (editables en el POS)
    pend = orden.items.filter(
        estado=OrdenItem.ESTADO_PENDIENTE,
        cancelado=False,
    )

    # Ya enviados / en preparación / servidos (solo lectura)
    enviados = orden.items.filter(
        estado__in=[
            OrdenItem.ESTADO_EN_PREP,
            OrdenItem.ESTADO_SERVIDO,
        ],
        cancelado=False,
    )

    data_pend = []
    for it in pend:
        precio = it.precio_unit or it.precio or Decimal("0.00")
        subtotal_row = precio * it.cantidad
        data_pend.append(
            {
                "id": it.id,
                "nombre": it.nombre,
                "cantidad": it.cantidad,
                "precio": str(precio),
                "subtotal": str(subtotal_row),
                "notas": it.notas or "",
            }
        )

    data_enviados = []
    for it in enviados:
        precio = it.precio_unit or it.precio or Decimal("0.00")
        subtotal_row = precio * it.cantidad
        data_enviados.append(
            {
                "id": it.id,
                "nombre": it.nombre,
                "cantidad": it.cantidad,
                "precio": str(precio),
                "subtotal": str(subtotal_row),
                "notas": it.notas or "",
                "estado": it.estado,
            }
        )

    total_general = sum(
        ( (it.precio_unit or it.precio or Decimal("0.00")) * it.cantidad )
        for it in orden.items.filter(cancelado=False)
    )

    return JsonResponse(
        {
            "ok": True,
            "pendientes": data_pend,
            "enviados": data_enviados,
            "total_general": str(total_general),
        }
    )


# === Eliminar un renglón ===
@staff_member_required
@require_POST
def api_orden_item_remove(request):
    """
    Payload JSON:
    { "orden_id": 123, "item_id": 456 }
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido."}, status=400)

    orden_id = int(data.get("orden_id") or 0)
    item_id = int(data.get("item_id") or 0)
    if not orden_id or not item_id:
        return JsonResponse({"ok": False, "error": "Faltan IDs."}, status=400)

    orden = get_object_or_404(Orden, pk=orden_id)
    item = get_object_or_404(OrdenItem, pk=item_id, orden=orden)
    item.delete()

    html = _render_modal(orden)
    return JsonResponse({"ok": True, "html": html})


# ======================================================================
# Enviar orden POS a cocina (crear Order/OrderItem legacy para KDS)
# ======================================================================

@staff_member_required
@require_POST
def api_orden_enviar_cocina(request, orden_id: int):
    """
    Endpoint JSON simple: marca la Orden como ENVIADA a cocina.
    (Lo puedes seguir usando donde ya lo tengas.)
    """
    orden = get_object_or_404(Orden, pk=orden_id)

    if not orden.items.exists():
        return JsonResponse(
            {"ok": False, "error": "La orden está vacía."},
            status=400,
        )

    orden.estado = "ENVIADA"
    orden.save(update_fields=["estado"])

    return JsonResponse({"ok": True, "message": "Orden enviada a cocina."})
# arriba: asegúrate de tener este import


@login_required
@user_passes_test(_is_staff)
@require_POST
def api_orden_pos_enviar_cocina(request, orden_id: int):
    """
    Envía la orden a cocina SIN tocar los items.
    Solo cambia el status y pone submitted_at si no existe.
    """
    orden = get_object_or_404(
        Order.objects.select_related("mesa", "sucursal"),
        pk=orden_id,
    )

    # No permitir enviar una orden cerrada
    if orden.status == OrderStatus.CLOSED:
        return JsonResponse({"ok": False, "error": "La orden ya está cerrada."}, status=400)

    # No permitir enviar si no hay productos activos
    if not orden.orderitem_set.filter(cancelado=False).exists():
        return JsonResponse({"ok": False, "error": "La orden está vacía."}, status=400)

    # Cambiar estado -> SUBMITTED (enviada a cocina)
    orden.status = OrderStatus.SUBMITTED
    if not orden.submitted_at:
        orden.submitted_at = timezone.now()
    orden.save(update_fields=["status", "submitted_at"])

    # Recalcular totales si existe el método
    if hasattr(orden, "compute_totals_live"):
        totals = orden.compute_totals_live()
    else:
        totals = {}

    mesa = orden.mesa
    sucursal = mesa.sucursal
    ahora_local = timezone.localtime()

    # Renderizar de nuevo SOLO el cuerpo del modal
    html = render_to_string(
        "reservas/orden_modal_body.html",
        {
            "mesa": mesa,
            "sucursal": sucursal,
            "orden": orden,
            "totals": totals,
            "ahora_local": ahora_local,
            "endpoint_add": reverse("reservas:api_orden_pos_add_item"),
            "endpoint_buscar": reverse("reservas:api_orden_pos_buscar_producto"),
            "endpoint_item_update": reverse("reservas:api_orden_pos_item_update", args=[orden.id]),
            "endpoint_item_split": reverse("reservas:api_orden_pos_item_split", args=[orden.id]),
            "endpoint_item_remove": reverse("reservas:api_orden_pos_item_remove", args=[orden.id]),
        },
        request=request,
    )

    return JsonResponse({"ok": True, "html": html})



# =========================================================
# POS: Cobrar y cerrar la orden (puente a Order legacy)
# =========================================================


@staff_member_required
@require_POST
def api_orden_pos_cobrar(request, orden_id: int):
    """
    Cobra la Orden POS y la marca como CERRADA.
    Opcional: regresa URL del ticket.
    """
    orden = get_object_or_404(
        Orden.objects.select_related("mesa", "sucursal"),
        pk=orden_id,
    )

    # Aquí podrías leer JSON para propina / método de pago si quieres
    # data = json.loads(request.body or "{}")

    # 💰 marcar como CERRADA
    orden.estado = Orden.ESTADO_CERRADA
    orden.cerrada_en = timezone.now()
    orden.save(update_fields=["estado", "cerrada_en"])

    # Si ya tienes view de ticket, arma la URL:
    ticket_url = None
    try:
        from django.urls import reverse
        ticket_url = reverse("reservas:ticket_order", args=[orden.id])
    except Exception:
        ticket_url = None

    return JsonResponse({
        "ok": True,
        "ticket_url": ticket_url,
    })



@staff_member_required
@require_POST
def api_sync_item_servido(request, legacy_item_id):
    """
    Cuando un OrderItem (legacy) es marcado como SERVIDO en el KDS,
    sincronizamos el estado equivalente en OrdenItem del POS.
    """
    legacy_item = get_object_or_404(LegacyOrderItem, pk=legacy_item_id)

    # Buscamos el item POS equivalente por nombre + precio + cantidad
    pos_item = (
        OrdenItem.objects.filter(
            orden__mesa=legacy_item.order.mesa,
            nombre=legacy_item.nombre,
            cantidad=legacy_item.cantidad,
            precio_unit=legacy_item.precio_unitario,
            estado=OrdenItem.ESTADO_EN_PREP,
            cancelado=False,
        )
        .order_by("id")
        .first()
    )

    if pos_item:
        pos_item.estado = OrdenItem.ESTADO_SERVIDO
        pos_item.save(update_fields=["estado"])

        # si TODOS están servidos, actualizamos la orden POS
        orden = pos_item.orden
        if not orden.items.filter(
            cancelado=False,
            estado__in=[OrdenItem.ESTADO_PENDIENTE, OrdenItem.ESTADO_EN_PREP]
        ).exists():
            orden.estado = "SERVIDO"
            orden.save(update_fields=["estado"])

    return JsonResponse({"ok": True})



# ============================
#  SINCRONIZAR KDS → POS
# ============================

@csrf_exempt
@login_required
@user_passes_test(_is_staff)
@require_POST
def orden_sync_servido(request, order_id: int):
    """
    Cuando en el KDS un Order (legacy) se marca como SERVED,
    marcamos como SERVIDO los renglones EN_PREP de la Orden POS
    de esa misma mesa.

    Esto solo actualiza estados; no toca montos.
    """
    # Order = modelo legacy (KDS / ticket)
    order = get_object_or_404(
        Order.objects.select_related("mesa"),
        pk=order_id,
    )
    mesa = order.mesa
    if not mesa:
        return JsonResponse({"ok": True, "detail": "Order sin mesa, nada que sincronizar."})

    # Buscar la Orden POS más reciente de esa mesa que no esté cerrada/cancelada
    try:
        orden_pos = (
            Orden.objects
            .filter(mesa=mesa)
            .exclude(estado__in=["CERRADA", "CANCELADA"])
            .latest("id")
        )
    except Orden.DoesNotExist:
        return JsonResponse({"ok": True, "detail": "Sin Orden POS ligada."})

    # Actualizar todos los items EN_PREP a SERVIDO
    updated = orden_pos.items.filter(
        cancelado=False,
        estado=OrdenItem.ESTADO_EN_PREP,
    ).update(estado=OrdenItem.ESTADO_SERVIDO)

    # (Opcional) si TODO quedó servido, podrías marcar la orden POS como SERVIDO
    # if not orden_pos.items.filter(cancelado=False).exclude(
    #         estado=OrdenItem.ESTADO_SERVIDO
    # ).exists():
    #     orden_pos.estado = "SERVIDO"
    #     orden_pos.save(update_fields=["estado"])

    return JsonResponse({"ok": True, "updated": updated})




# si ya tienes este helper, úsalo; si no, puedes dejarlo así:
def _is_staff(user):
    return user.is_active and user.is_staff


@csrf_exempt
@login_required
@user_passes_test(_is_staff)
@require_POST
def api_orden_pos_cobrar(request, orden_id: int):
    """
    Toma una Orden (POS nuevo) y genera/actualiza un Order legacy,
    recalcula totales y devuelve la URL del ticket.
    """
    orden = get_object_or_404(
        Orden.objects.select_related("sucursal", "mesa", "reserva"),
        pk=orden_id,
    )

    # No permitir cobrar varias veces
    if orden.estado in ["CERRADA", "CANCELADA"]:
        return JsonResponse(
            {"ok": False, "error": "La orden ya está cerrada o cancelada."},
            status=400,
        )

    # Solo renglones activos
    items_qs = orden.items.filter(cancelado=False)
    if not items_qs.exists():
        return JsonResponse(
            {"ok": False, "error": "La orden no tiene productos activos."},
            status=400,
        )

    with transaction.atomic():
        # 1) Crear Order legacy para ticket/cocina
        kds_order = Order.objects.create(
            sucursal=orden.sucursal,
            mesa=orden.mesa,
            reserva=orden.reserva,
            status=OrderStatus.SUBMITTED,
            creado_por=request.user,
        )

        # 2) Pasar los renglones al OrderItem legacy
        for it in items_qs:
            precio_unitario = it.precio or it.precio_unit or Decimal("0.00")
            LegacyOrderItem.objects.create(
                order=kds_order,
                nombre=it.nombre,
                precio_unitario=precio_unitario,
                cantidad=it.cantidad,
                notas=it.notas,
                enviado_a_cocina=True,  # ya está servido en POS
            )

        # 3) Recalcular totales usando tu helper actual
        totals = kds_order.compute_totals_live()
        kds_order.subtotal_base = totals["subtotal_base"]
        kds_order.iva_total = totals["iva_total"]
        kds_order.total_bruto = totals["total_bruto"]
        kds_order.total_con_propina = totals.get(
            "total_con_propina",
            totals["total_bruto"],
        )
        kds_order.status = OrderStatus.CLOSED  # o el que uses para cobrada
        kds_order.save()

        # 4) Marcar Orden POS como CERRADA
        orden.estado = "CERRADA"
        orden.save(update_fields=["estado"])

    ticket_url = reverse("reservas:ticket_order", args=[kds_order.id])
    return JsonResponse({"ok": True, "ticket_url": ticket_url})
