# reservas/views_storelocator.py
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, date as date_cls, time as time_cls
from django.http import JsonResponse
from django.shortcuts import render
from django.apps import apps
from django.db.models import Q
from django.core.paginator import Paginator

# Evita import circular si mueves modelos
Sucursal = apps.get_model("reservas", "Sucursal")


# =============================== Helpers ===============================

def _haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en KM entre dos coordenadas (WGS84)."""
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def _branch_to_dict(s):
    """Serializa una sucursal para respuestas JSON."""
    return {
        "id": s.id,
        "nombre": s.nombre,
        "slug": s.slug,
        "lat": float(s.lat) if s.lat is not None else None,
        "lng": float(s.lng) if s.lng is not None else None,
        "direccion": getattr(s, "direccion", ""),
        "cp": getattr(s, "codigo_postal", ""),
        "portada": s.portada.url if getattr(s, "portada", None) else None,
        "precio": getattr(s, "precio_nivel", ""),
        "rating": float(getattr(s, "rating", 0) or 0),
        "reviews": getattr(s, "reviews", 0),
        "recomendado": getattr(s, "recomendado", False),
    }


def _coerce_date(date_str):
    """Convierte YYYY-MM-DD a date. Si viene vacío, devuelve hoy."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return datetime.now().date()


def _coerce_time(time_str):
    """Convierte HH:MM a time. Si viene vacío, devuelve hora/min actual."""
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except Exception:
        now = datetime.now()
        return time_cls(now.hour, now.minute)


def _format_slot(slot_obj):
    """
    Convierte un time/datetime a string legible 'h:mm am/pm'.
    Si ya es cadena, la regresa tal cual.
    """
    if isinstance(slot_obj, str):
        return slot_obj
    if isinstance(slot_obj, datetime):
        t = slot_obj.time()
    elif isinstance(slot_obj, time_cls):
        t = slot_obj
    else:
        return str(slot_obj)
    # Formato 12h con am/pm en minúsculas
    txt = t.strftime("%I:%M %p")
    return txt.lstrip("0").lower()


def _slots_for(sucursal, d: date_cls, t: time_cls, party: int):
    """
    Obtiene próximos horarios disponibles de la sucursal.
    Llama de forma defensiva distintos posibles métodos para no romper compatibilidad:
      - sucursal.proximos_slots_para(date, time, party)
      - sucursal.get_proximos_slots(date, time, party)
      - sucursal.proximos_slots()
    Devuelve lista de strings.
    """
    # 1) Intento con firma completa (date, time, party)
    for attr in ("proximos_slots_para", "get_proximos_slots"):
        func = getattr(sucursal, attr, None)
        if callable(func):
            try:
                raw = func(d, t, party)
                slots = list(raw) if raw is not None else []
                return [_format_slot(x) for x in slots]
            except TypeError:
                # La firma no coincide; probamos con menos args.
                try:
                    raw = func(d, party)
                    slots = list(raw) if raw is not None else []
                    return [_format_slot(x) for x in slots]
                except Exception:
                    pass
            except Exception:
                pass

    # 2) Método sin args
    func = getattr(sucursal, "proximos_slots", None)
    if callable(func):
        try:
            raw = func()
            slots = list(raw) if raw is not None else []
            return [_format_slot(x) for x in slots]
        except Exception:
            pass

    # 3) Nada disponible
    return []


# =============================== APIs JSON ===============================

def api_sucursales(request):
    """
    Lista de sucursales (JSON) con lat/lng válidos.
    """
    qs = Sucursal.objects.filter(activo=True, lat__isnull=False, lng__isnull=False)
    return JsonResponse({"results": [_branch_to_dict(s) for s in qs]})


def api_sucursales_nearby(request):
    """
    Sucursales cercanas a lat/lng dentro de 'km' km (JSON).
    """
    try:
        lat = float(request.GET.get("lat"))
        lng = float(request.GET.get("lng"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "lat/lng requeridos"}, status=400)

    km = float(request.GET.get("km", 25))
    out = []
    for s in Sucursal.objects.filter(activo=True, lat__isnull=False, lng__isnull=False):
        d = _haversine_km(lat, lng, float(s.lat), float(s.lng))
        if d <= km:
            row = _branch_to_dict(s)
            row["dist_km"] = round(d, 2)
            out.append(row)
    out.sort(key=lambda x: x["dist_km"])
    return JsonResponse({"results": out})


# =================== Página de selección de sucursal ====================

def seleccionar_sucursal(request):
    """
    Página 'Encontrar mesa':
    - Aplica búsqueda por texto (q).
    - Si viene lat/lng, ordena por cercanía y añade dist_km.
    - Devuelve 'results' con {'obj', 'dist_km', 'proximos_slots'}.
    - Paginación con page_obj.
    - Entrega también 'sucursales_carrusel' para el carrusel reutilizable.
    - Mantiene 'sucursales' (compatibilidad) como lista simple con 'obj' y 'dist_km'.
    """
    # --------- parámetros de filtro (con defaults seguros) ---------
    q = (request.GET.get("q") or "").strip()
    date_str = request.GET.get("date") or datetime.now().date().strftime("%Y-%m-%d")
    time_str = request.GET.get("time") or datetime.now().strftime("%H:%M")
    party_str = request.GET.get("party") or "2"

    d = _coerce_date(date_str)
    t = _coerce_time(time_str)
    try:
        party = int(party_str)
    except Exception:
        party = 2

    # --------- queryset base ---------
    qs = Sucursal.objects.filter(activo=True, lat__isnull=False, lng__isnull=False)
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) |
            Q(ciudad__icontains=q) |
            Q(direccion__icontains=q)
        )

    # --------- orden por cercanía si viene geo ---------
    lat = request.GET.get("lat")
    lng = request.GET.get("lng")
    user_coords = None

    items = []
    if lat and lng:
        try:
            ulat, ulng = float(lat), float(lng)
            user_coords = {"lat": ulat, "lng": ulng}
            for s in qs:
                dkm = _haversine_km(ulat, ulng, float(s.lat), float(s.lng))
                items.append({"obj": s, "dist_km": round(dkm, 2)})
            items.sort(key=lambda r: r["dist_km"])
        except ValueError:
            # Geo inválida → sin distancia
            items = [{"obj": s, "dist_km": None} for s in qs]
    else:
        items = [{"obj": s, "dist_km": None} for s in qs]

    # --------- proximos_slots por sucursal (defensivo) ---------
    results = []
    for row in items:
        s = row["obj"]
        slots = _slots_for(s, d, t, party)
        results.append({
            "obj": s,
            "dist_km": row["dist_km"],
            "proximos_slots": slots[:3],  # muestra 3 como en tu UI
        })

    # --------- paginación ---------
    page = request.GET.get("page") or 1
    paginator = Paginator(results, 12)  # 12 cards por página
    page_obj = paginator.get_page(page)

    # --------- dataset para el carrusel ---------
    # Puedes ajustar el criterio (recomendado=True, por rating, etc.)
    sucursales_carrusel = (
        Sucursal.objects.filter(activo=True)
        .order_by("-rating", "nombre")[:12]
    )

    # --------- compatibilidad: 'sucursales' simple ---------
    # (algunas plantillas antiguas podrían usarla)
    sucursales_simple = [{"obj": r["obj"], "dist_km": r["dist_km"]} for r in results]

    ctx = {
        # Filtros y valores activos
        "q": q,
        "date": d.strftime("%Y-%m-%d"),
        "time": t.strftime("%H:%M"),
        "party": str(party),
        "party_range": range(1, 13),

        # Resultados
        "results": page_obj.object_list,
        "page_obj": page_obj,

        # Geo info (para UI)
        "user_coords": user_coords,
        "has_geo": bool(user_coords),

        # Carrusel
        "sucursales_carrusel": sucursales_carrusel,

        # Compat
        "sucursales": sucursales_simple,
    }
    return render(request, "reservas/seleccionar_sucursal.html", ctx)


# (opcional) vista del mapa público simple
def store_locator(request):
    return render(request, "public/store_locator.html")
