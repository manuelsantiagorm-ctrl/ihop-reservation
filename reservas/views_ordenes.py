# reservas/views_ordenes.py
from decimal import Decimal
import json

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt 
from django.views.decorators.http import require_POST
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction

# Modelos propios
from .models import Mesa
from .models_orders import Orden, OrdenItem
from .models_menu import CatalogItem  # Catálogo global

# === Config ===
TEMPLATE_ORDER_MODAL = "reservas/partials/orden_modal.html"
IVA_DEFAULT = Decimal("0.16")


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


def _render_modal(orden):
    items_qs = orden.items.all().order_by("id")

    items = []
    subtotal = Decimal("0.00")
    for it in items_qs:
        precio = it.precio_unit or Decimal("0.00")
        importe = (precio * (it.cantidad or 0)).quantize(Decimal("0.01"))
        subtotal += importe
        items.append({
            "id": it.id,
            "nombre": it.nombre,
            "cantidad": it.cantidad,
            "precio": f"${precio:.2f}",
            "importe": f"${importe:.2f}",
            "notas": it.notas or "",
        })

    iva   = (subtotal * Decimal("0.16")).quantize(Decimal("0.01"))
    total = (subtotal + iva).quantize(Decimal("0.01"))

    ctx = {
        "orden": orden,
        "mesa": orden.mesa,
        "sucursal": orden.sucursal,
        "ahora_local": timezone.localtime(),
        "items": items,
        "subtotal": subtotal,
        "impuestos": iva,
        "total": total,
        # === Endpoints que inyectamos al HTML ===
        "endpoint_buscar": reverse("reservas:menu_api_buscar"),
        "endpoint_add": reverse("reservas:api_orden_crear"),
        "endpoint_item_update": reverse("reservas:api_orden_item_update"),
        "endpoint_item_split": reverse("reservas:api_orden_item_split"),
        "endpoint_item_remove": reverse("reservas:api_orden_item_remove"),  # <-- FALTABA
    }
    return render_to_string("reservas/partials/orden_modal.html", ctx)



# =========================================================
# Vistas
# =========================================================
@staff_member_required
@require_GET
def orden_mesa_nueva(request):
    """
    Abre (o crea) una orden ABIERTA para la mesa dada y
    devuelve el HTML del modal.
    GET /orden/nueva/?mesa_id=ID
    """
    mesa_id = int(request.GET.get("mesa_id") or 0)
    if not mesa_id:
        return HttpResponseBadRequest("Falta mesa_id")

    mesa = get_object_or_404(Mesa.objects.select_related("sucursal"), pk=mesa_id)
    orden = _get_or_create_open_order(mesa)

    html = _render_modal(orden)
    # Devolvemos HTML directo (el JS lo acepta como text)
    return HttpResponse(html)


@staff_member_required
@require_GET
def api_menu_buscar(request):
    """
    Autocomplete para el buscador del modal.
    Soporta catálogos con/ sin 'codigo' (usa 'nombre' como fallback).
    Responde: {"results": [{"codigo","nombre","precio"}, ...]}
    """
    q = (request.GET.get("q") or "").strip()

    qs = CatalogItem.objects.filter(activo=True)
    if q:
        # si hay campo 'codigo' lo usamos, si no sólo nombre
        if hasattr(CatalogItem, "codigo"):
            qs = qs.filter(Q(nombre__icontains=q) | Q(codigo__icontains=q))
        else:
            qs = qs.filter(nombre__icontains=q)

    qs = qs.select_related("categoria").order_by("categoria__orden", "nombre")[:25]

    results = []
    for obj in qs:
        codigo = getattr(obj, "codigo", None) or obj.nombre  # fallback
        precio = getattr(obj, "precio", None)
        if precio is None:
            precio = getattr(obj, "price", 0)
        results.append({
            "codigo": str(codigo),
            "nombre": str(obj.nombre),
            "precio": float(precio or 0),
        })

    return JsonResponse({"results": results})


@staff_member_required
@require_POST
def api_orden_crear(request):
    """
    Agrega un ítem del catálogo a una orden EXISTENTE.
    - Prohíbe ítems “libres”.
    - Siempre usa el precio del menú.
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
        return JsonResponse({"ok": False, "error": "Faltan datos requeridos."}, status=400)

    # Orden existe
    orden = get_object_or_404(Orden, pk=orden_id)

    # Buscar en catálogo: soporta 'codigo' o 'nombre' como código
    if hasattr(CatalogItem, "codigo"):
        item = CatalogItem.objects.filter(activo=True, codigo__iexact=codigo).first()
        if not item:
            # como respaldo, permite buscar por nombre exacto
            item = CatalogItem.objects.filter(activo=True, nombre__iexact=codigo).first()
    else:
        item = CatalogItem.objects.filter(activo=True, nombre__iexact=codigo).first()

    if not item:
        return JsonResponse({"ok": False, "error": "El código no existe en el Menú."}, status=400)

    # Tomar SIEMPRE el precio del menú
    precio = getattr(item, "precio", None)
    if precio is None:
        precio = getattr(item, "price", None)
    if precio is None:
        return JsonResponse({"ok": False, "error": "El ítem de menú no tiene precio."}, status=500)

    categoria_nombre = ""
    cat = getattr(item, "categoria", None)
    if cat is not None:
        categoria_nombre = getattr(cat, "nombre", "") or getattr(cat, "name", "") or ""

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
def api_orden_add_item(request):
    """
    Compatibilidad con rutas antiguas: delega al endpoint nuevo.
    """
    return api_orden_crear(request)



# --- dentro de views_ordenes.py ---

 # (no lo uses si ya manejas CSRF en fetch)

@require_POST
@staff_member_required
def api_orden_quitar_item(request):
    """
    Elimina un renglón de la orden y devuelve el HTML actualizado del modal.
    Body JSON: { "orden_id": <int>, "item_id": <int> }
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "Payload inválido."}, status=400)

    orden_id = int(data.get("orden_id") or 0)
    item_id  = int(data.get("item_id") or 0)
    if not orden_id or not item_id:
        return JsonResponse({"ok": False, "error": "Faltan datos."}, status=400)

    orden = get_object_or_404(Orden, pk=orden_id)
    item  = get_object_or_404(OrdenItem, pk=item_id, orden=orden)

    # estrategia simple: borrar renglón
    item.delete()

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

    item_id   = int(data.get("item_id") or 0)
    orden_id  = int(data.get("orden_id") or 0)
    notas     = (data.get("notas") or "").strip()
    cantidad  = int(data.get("cantidad") or 0)

    if not item_id or not orden_id:
        return JsonResponse({"ok": False, "error": "Faltan IDs."}, status=400)

    item = get_object_or_404(OrdenItem, pk=item_id, orden_id=orden_id)
    if cantidad <= 0:
        return JsonResponse({"ok": False, "error": "Cantidad inválida."}, status=400)

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

    item_id        = int(data.get("item_id") or 0)
    orden_id       = int(data.get("orden_id") or 0)
    cantidad_nueva = int(data.get("cantidad_nueva") or 0)
    notas_nuevas   = (data.get("notas_nuevas") or "").strip()

    if not item_id or not orden_id or cantidad_nueva <= 0:
        return JsonResponse({"ok": False, "error": "Datos incompletos."}, status=400)

    item = get_object_or_404(OrdenItem, pk=item_id, orden_id=orden_id)
    if cantidad_nueva >= item.cantidad:
        return JsonResponse({"ok": False, "error": "La cantidad a dividir debe ser menor a la actual."}, status=400)

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




# Asegúrate de tener estos imports arriba del archivo también:
# from .models_orders import Orden, OrdenItem
# from django.template.loader import render_to_string
# from django.utils import timezone

@staff_member_required
@require_GET
def api_orden_detalle(request, orden_id):
    """
    Devuelve el HTML del modal actualizado para una orden existente.
    """
    orden = get_object_or_404(
        Orden.objects.select_related("sucursal", "mesa"),
        pk=orden_id
    )
    html = _render_modal(orden)
    return JsonResponse({"ok": True, "orden_id": orden.id, "html": html})



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
    item_id  = int(data.get("item_id") or 0)
    if not orden_id or not item_id:
        return JsonResponse({"ok": False, "error": "Faltan IDs."}, status=400)

    orden = get_object_or_404(Orden, pk=orden_id)
    item  = get_object_or_404(OrdenItem, pk=item_id, orden=orden)
    item.delete()

    html = _render_modal(orden)
    return JsonResponse({"ok": True, "html": html})
