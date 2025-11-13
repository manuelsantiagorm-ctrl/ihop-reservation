# reservas/views.py
import os
import json
import logging
from math import radians, cos, sin, asin, sqrt
from datetime import datetime, date, time, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import (
    login_required, user_passes_test, permission_required
)
# BIEN: importar desde models_orders
from .models_orders import Orden, OrdenItem, Order, OrderItem as POSOrderItem

# Si usas catálogo nuevo en las vistas:
from .models_menu import CatalogItem
# Y los core (mesa/sucursal/reserva) siguen en models.py:
from .models import Sucursal, Mesa, Reserva


# Catálogo nuevo (si tu búsqueda usa catálogo)
from .models_menu import CatalogItem
from django.template.loader import render_to_string
from datetime import timezone as py_tz  # <-- para usar py_tz.utc en vez de timezone.utc
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.db.models import (
    Q, Exists, OuterRef, Value, BooleanField, Case, When, Max, Count
)
from django.http import (
    JsonResponse, HttpResponse, HttpResponseForbidden,
    HttpResponseRedirect, HttpResponseBadRequest, Http404
)
from reservas.services_orders import liberar_preorden_al_checkin

from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone, formats
from django.utils import timezone as dj_tz
from django.utils.dateparse import parse_datetime, parse_date
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET, require_POST, require_http_methods
)

from .permissions import assert_user_can_manage_sucursal  # <-- IMPORTANTE
from .helpers.permisos import assert_can_manage
from .utils_auth import scope_sucursales_for, user_allowed_countries
from .utils_country import get_effective_country
from .utils import (
    mesas_disponibles_para_reserva, mover_reserva,
    booking_total_minutes, asignar_mesa_automatica
)
from .emails import enviar_correo_reserva_confirmada
from .forms import (
    WalkInReservaForm, ClientePerfilForm, ClienteRegistrationForm,
    ReservaForm, SucursalForm, SucursalFotoForm, SucursalFotoFormSet,
)
from .models import (
    Cliente, Mesa, Reserva, Sucursal, SucursalFoto,
    PerfilAdmin, BloqueoMesa,
)

def _get_reserva_by_folio(folio: str):
    # Búsqueda case-insensitive por folio exacto
    return get_object_or_404(Reserva, folio__iexact=folio.strip())

@login_required
def reserva_scan_entry(request, folio):
    r = get_object_or_404(
        Reserva.objects.select_related("sucursal", "mesa", "cliente", "cliente__user"),
        folio=folio,
    )

    # TZ sucursal y textos de fecha/hora/duración
    tz = _tz_for_sucursal(r.sucursal or (r.mesa and r.mesa.sucursal))
    li = r.local_inicio or (r.inicio_utc and timezone.localtime(r.inicio_utc, tz))
    lf = r.local_fin or (r.fin_utc and timezone.localtime(r.fin_utc, tz))
    fecha_txt = formats.date_format(li.date(), "DATE_FORMAT") if li else ""
    hora_txt = li.strftime("%H:%M") if li else ""
    duracion_min = int(((lf - li).total_seconds() // 60)) if (li and lf) else 0

    ctx = {
        "reserva": r,
        "fecha_txt": fecha_txt,
        "hora_txt": hora_txt,
        "duracion_min": duracion_min,
        "personas": r.num_personas,
        "for_staff": request.user.is_staff,
        **_contacto_from_reserva(r),
    }
    return render(request, "reservas/reserva_scan_entry.html", ctx)

@require_POST
@login_required
def reserva_checkin(request, folio):
    if not request.user.is_staff:
        return HttpResponseForbidden("Solo personal autorizado")

    reserva = _get_reserva_by_folio(folio)
    reserva.llego = True
    reserva.checkin_at = dj_tz.now()
    reserva.arrived_at = reserva.checkin_at
    if hasattr(reserva, "estado") and not reserva.estado:
        pass
    reserva.save(update_fields=["llego", "checkin_at", "arrived_at"])

    # ✅ Liberar pre-orden al hacer check-in
    from reservas.services_orders import liberar_preorden_al_checkin
    liberar_preorden_al_checkin(reserva)

    messages.success(request, "¡Check-in registrado y pedido enviado a cocina!")
    return redirect("reservas:reserva_scan_entry", folio=reserva.folio)






# --- Rate limit (shim para que migrate no truene si falta la lib) ---
try:
    from ratelimit.decorators import ratelimit
except Exception:
    def ratelimit(*args, **kwargs):
        def _inner(view):
            return view
        return _inner


def _activate_sucursal_tz(sucursal):
    """Activa la zona horaria local de la sucursal para esta request."""
    try:
        dj_tz.activate(ZoneInfo(sucursal.timezone))
    except Exception:
        # Fallback: no rompas si el nombre está mal
        dj_tz.deactivate()




def _tz_for_sucursal(s) -> timezone.tzinfo:
    """
    Devuelve la TZ de una sucursal.
    Intenta, en orden: s.timezone (o zona_horaria), s.pais.tz; si falla, usa TZ actual de Django.
    """
    # nombres posibles que tú usas en tus modelos
    posibles = ("timezone", "zona_horaria", "tz",)
    tzname = None

    for attr in posibles:
        val = getattr(s, attr, None)
        if val:
            tzname = val
            break

    # intentar via país (s.pais.tz)
    if not tzname:
        try:
            tzname = getattr(getattr(s, "pais", None), "tz", None)
        except Exception:
            tzname = None

    if tzname and ZoneInfo:
        try:
            return ZoneInfo(tzname)
        except Exception:
            pass

    return timezone.get_current_timezone()

# ===================================================================
# Constantes y utilidades internas
# ===================================================================

STEP_MIN = 15  # genera slots cada 15 min
logger = logging.getLogger("reservas.mail")

def _ensure_staff_or_404(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        raise Http404()


def _overlap(a_start, a_end, b_start, b_end):
    return not (a_end <= b_start or a_start >= b_end)


def _es_staff(user):
    return user.is_staff


def _en_ventana_debug_o_ajax(request):
    if settings.DEBUG:
        return True
    if request.user.is_authenticated and request.user.is_staff:
        return True
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _parse_fecha_param(fecha_qs: str):
    """
    Acepta 'YYYY-MM-DD' (ISO) o 'DD/MM/YYYY' y devuelve date().
    Si viene vacío o inválido, regresa hoy (timezone.localdate()).
    """
    if not fecha_qs:
        return timezone.localdate()
    fecha_qs = fecha_qs.strip()
    try:
        return date.fromisoformat(fecha_qs)  # 2025-09-19
    except Exception:
        pass
    try:
        d, m, y = [int(x) for x in fecha_qs.replace(".", "/").split("/")[:3]]  # 19/09/2025
        return date(y, m, d)
    except Exception:
        return timezone.localdate()



def _round_to_next_15(dt: datetime) -> datetime:
    minute = (dt.minute // 15 + 1) * 15
    carry = minute // 60
    minute = minute % 60
    return dt.replace(minute=minute, second=0, microsecond=0) + timedelta(hours=carry)





def _slot_consultado(request):
    """
    Lee ?fecha=YYYY-MM-DD & ?hora=HH:MM y devuelve (inicio, fin) aware.
    Si no vienen, usa el siguiente bloque de 30 minutos desde 'ahora'.
    """
    tz = timezone.get_current_timezone()
    f = request.GET.get("fecha")
    h = request.GET.get("hora")

    if f and h:
        inicio = timezone.make_aware(datetime.strptime(f"{f} {h}", "%Y-%m-%d %H:%M"), tz)
    else:
        now = timezone.localtime()
        minute = ((now.minute // 30) + 1) * 30
        if minute == 60:
            inicio = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            inicio = now.replace(minute=minute, second=0, microsecond=0)

    total_min = int(getattr(settings, "RESERVA_TOTAL_MINUTOS", 70))
    fin = inicio + timedelta(minutes=booking_total_minutes(inicio, party=2))

    return inicio, fin


# ===================================================================
# HOME / REGISTRO / PERFIL
# ===================================================================


# ===============================
#   HOME
# ===============================

@login_required
def home(request):
    user = request.user
    is_admin_staff = user.is_staff

    # ---- Qué sucursales mostrar en el panel “Admin de sucursal” ----
    if user.is_superuser:
        admin_sucursales = Sucursal.objects.all().order_by("nombre")
    else:
        allowed = user_allowed_countries(user)  # queryset de países permitidos
        if allowed.exists():
            # Country Admin: solo sucursales de sus países
            admin_sucursales = (
                Sucursal.objects.filter(pais_id__in=allowed.values_list("id", flat=True))
                .order_by("nombre")
            )
        elif is_admin_staff:
            # Branch Admin: solo sucursales donde es administrador
            admin_sucursales = Sucursal.objects.filter(administradores=user).order_by("nombre")
        else:
            admin_sucursales = Sucursal.objects.none()

    # ---- Listado público (para clientes) ----
    if not user.is_staff:
        user_country = get_effective_country(request)
        todas = Sucursal.objects.filter(activo=True, pais=user_country).order_by("nombre")
    else:
        todas = scope_sucursales_for(request, Sucursal.objects.filter(activo=True).order_by("nombre"))

    # ===== Carrusel: 12 sucursales =====
    sucursales = list(todas[:12])

    def fmt(t: time) -> str:
        return (
            t.strftime("%I:%M %p")
            .lower()
            .replace("am", "a. m.")
            .replace("pm", "p. m.")
            .lstrip("0")
        )

    sugerencias_mock = [fmt(time(13, 0)), fmt(time(13, 15)), fmt(time(13, 30))]
    for s in sucursales:
        s.sugerencias = sugerencias_mock

    # ===== Recomendadas / Otras (por CP del cliente) =====
    cliente = getattr(user, "cliente", None)
    recomendadas_qs = Sucursal.objects.none()
    otras_qs = todas
    if cliente and getattr(cliente, "codigo_postal", None):
        cp = (cliente.codigo_postal or "").strip()
        if cp:
            exactas = todas.filter(codigo_postal=cp)
            if exactas.exists():
                recomendadas_qs = exactas
                otras_qs = todas.exclude(id__in=exactas.values("id"))
            else:
                pref = cp[:3]
                similares = todas.filter(codigo_postal__startswith=pref)
                if similares.exists():
                    recomendadas_qs = similares
                    otras_qs = todas.exclude(id__in=similares.values("id"))

    ctx = {
        "is_admin_staff": is_admin_staff,
        "admin_sucursales": admin_sucursales,
        "sucursales": sucursales,
        "sucursales_recomendadas": recomendadas_qs,
        "otras_sucursales": otras_qs,
        "hoy": timezone.localdate(),
        "party_range": range(1, 13),
        "party_default": "2",
        "user_country": locals().get("user_country", None),  # 👈 agregado
    }
    return render(request, "reservas/home.html", ctx)

@login_required
def perfil(request):
    cliente, _ = Cliente.objects.get_or_create(
        user=request.user,
        defaults={
            "nombre": request.user.get_full_name() or request.user.username,
            "email": request.user.email or "",
        },
    )

    if request.method == "POST":
        form = ClientePerfilForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            messages.success(request, "Perfil actualizado ✅")
            return redirect("reservas:perfil")
        else:
            messages.error(request, "Revisa los campos del formulario.")
    else:
        form = ClientePerfilForm(instance=cliente)

    return render(request, "reservas/perfil.html", {"form": form})

# ===================================================================
# BÚSQUEDA / RESULTADOS (tipo OpenTable) + NearMe (lat/lng)
# ===================================================================


def _coords_from_sucursal(s):
    """
    Devuelve (lat, lng) o (None, None) buscando en varios nombres de campo:
    - PointField: ubicacion/location/geo/point (.y=lat, .x=lng)
    - Pares: (latitud,longitud), (latitude,longitude), (lat,lng), (lat,long)
    """
    # GeoDjango PointField
    for field in ("ubicacion", "location", "geo", "point"):
        val = getattr(s, field, None)
        if val is not None and hasattr(val, "x") and hasattr(val, "y"):
            try:
                return float(val.y), float(val.x)
            except Exception:
                pass

    # Pares comunes
    for a, b in (("latitud","longitud"), ("latitude","longitude"),
                 ("lat","lng"), ("lat","long")):
        la = getattr(s, a, None)
        lo = getattr(s, b, None)
        if la is not None and lo is not None:
            try:
                return float(la), float(lo)
            except Exception:
                continue

    return None, None


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1)*cos(lat2)*sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def seleccionar_sucursal(request):
    """
    Lista sucursales con filtro y orden de recomendadas o por distancia.
    GET: q, date (YYYY-MM-DD), time (HH:MM), party (int), page,
         lat, lng, radius_km | km
    """
    q = request.GET.get("q", "").strip()
    date_str = request.GET.get("date")
    time_str = request.GET.get("time")
    party = request.GET.get("party")
    lat = request.GET.get("lat")
    lng = request.GET.get("lng")

    radius_str = request.GET.get("radius_km", request.GET.get("km", "50"))
    try:
        radius_km = float(radius_str)
    except Exception:
        radius_km = 50.0

    # ---- Base y scoping por país ----
    if request.user.is_authenticated and request.user.is_staff:
        base_qs = Sucursal.objects.filter(activo=True)
        qs = scope_sucursales_for(request, base_qs)
    else:
        user_country = get_effective_country(request)
        qs = Sucursal.objects.filter(activo=True, pais=user_country)

    # ---- Filtro texto ----
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) |
            Q(direccion__icontains=q) |
            Q(codigo_postal__icontains=q) |
            Q(cocina__icontains=q)
        )

    # ---- Si es Branch Admin (sin países asignados) ----
    if (
        request.user.is_authenticated and request.user.is_staff
        and not request.user.is_superuser
        and not user_allowed_countries(request.user).exists()
    ):
        qs = qs.filter(administradores=request.user)

    # Helper: base_dt por sucursal (en su TZ)
    def _base_dt_for_sucursal(suc: Sucursal) -> datetime:
        tz = ZoneInfo(suc.timezone)
        if date_str:
            try:
                t = datetime.strptime(time_str or "19:00", "%H:%M").time()
                d = date.fromisoformat(date_str)
                return dj_tz.make_aware(datetime.combine(d, t), tz)
            except Exception:
                pass
        # si no viene fecha válida, usar ahora local de la sucursal
        return timezone.now().astimezone(tz)

    user_lat = user_lng = None
    results_raw = []

    # --- MODO CERCA DE MÍ ---
    if lat and lng:
        try:
            user_lat, user_lng = float(lat), float(lng)
        except ValueError:
            user_lat = user_lng = None

    if user_lat is not None and user_lng is not None:
        for s in qs:
            s_lat, s_lng = _coords_from_sucursal(s)
            d = None
            if s_lat is not None and s_lng is not None:
                d = _haversine_km(user_lat, user_lng, s_lat, s_lng)
                if d > radius_km:
                    continue
            tz = ZoneInfo(s.timezone)
            base_dt = _base_dt_for_sucursal(s)
            results_raw.append({
                "obj": s,
                "map_lat": s_lat,
                "map_lng": s_lng,
                "distance_km": (None if d is None else round(d, 1)),
                "proximos_slots": _proximos_slots(base_dt, 3, tz=tz),
            })
        results_raw.sort(key=lambda item: (item["distance_km"] is None, item["distance_km"] or 0.0))
    else:
        # --- MODO NORMAL ---
        for s in qs.order_by("-recomendado", "nombre"):
            s_lat, s_lng = _coords_from_sucursal(s)
            tz = ZoneInfo(s.timezone)
            base_dt = _base_dt_for_sucursal(s)
            results_raw.append({
                "obj": s,
                "map_lat": s_lat,
                "map_lng": s_lng,
                "distance_km": None,
                "proximos_slots": _proximos_slots(base_dt, 3, tz=tz),
            })

    paginator = Paginator(results_raw, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    ctx = {
        "q": q,
        "date": date_str or dj_tz.localdate().strftime("%Y-%m-%d"),
        "time": time_str or "19:00",
        "party": party or "2",
        "page_obj": page_obj,
        "results": list(page_obj.object_list),
        "party_range": range(1, 13),
        "user_lat": user_lat,
        "user_lng": user_lng,
        "radius_km": int(radius_km),
        "user_country": locals().get("user_country", None),
    }
    return render(request, "reservas/seleccionar_sucursal.html", ctx)



# --- Redirección directa desde "Ver disponibilidad" al detalle de sucursal ---


def seleccionar_sucursal_redirect(request):
    """
    Recibe ?id=<sucursal_id>&date=YYYY-MM-DD&time=HH:MM&party=N
    y redirige a /s/<slug>/?date=...&time=...&party=...
    """
    sucursal_id = request.GET.get("id") or request.GET.get("sucursal_id")
    if not sucursal_id:
        return redirect("reservas:store_locator")

    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
    detalle_url = reverse("reservas:sucursal_detalle", kwargs={"slug": sucursal.slug})

    params = {}
    for key in ("date", "time", "party"):
        val = request.GET.get(key)
        if val:
            params[key] = val

    if params:
        detalle_url = f"{detalle_url}?{urlencode(params)}"

    return redirect(detalle_url)



# ===================================================================
# HACER UNA RESERVA
# ===================================================================

@login_required
def reservar(request, mesa_id):
    from .utils import (
        anticipacion_minima_para,
        conflicto_y_disponible,
        _auto_cancel_por_tolerancia,
    )
    _auto_cancel_por_tolerancia(minutos=6)

    cliente, _ = Cliente.objects.get_or_create(
        user=request.user,
        defaults={
            "nombre": request.user.get_full_name() or request.user.username,
            "email":  request.user.email or "",
        },
    )

    mesa = get_object_or_404(Mesa, id=mesa_id)
    fecha_listado = timezone.localdate()

    if request.method == "POST":
        form = ReservaForm(request.POST, mesa=mesa, cliente=cliente)
        if form.is_valid():
            try:
                with transaction.atomic():
                    Mesa.objects.select_for_update().get(pk=mesa.pk)

                    fecha = form.cleaned_data["fecha"]
                    if timezone.is_naive(fecha):
                        fecha = timezone.make_aware(fecha, timezone.get_current_timezone())

                    tz = timezone.get_current_timezone()
                    now_loc = timezone.now().astimezone(tz)
                    fec_loc = fecha.astimezone(tz)
                    antic_min = anticipacion_minima_para(fec_loc)
                    if fec_loc < now_loc + timedelta(minutes=antic_min):
                        messages.error(request, f"Debes reservar con al menos {antic_min} minutos de anticipación.")
                        return redirect("reservas:reservar", mesa_id=mesa.id)

                    conflicto, hora_disp = conflicto_y_disponible(mesa, fecha)
                    if conflicto:
                        messages.error(
                            request,
                            "⚠ La mesa está ocupada hasta las "
                            f"{hora_disp.astimezone(tz).strftime('%H:%M')}."
                        )
                        return redirect("reservas:reservar", mesa_id=mesa.id)

                    if not request.user.is_staff:
                        sep_min = int(getattr(settings, "RESERVA_MIN_SEPARACION_MIN", 120))
                        por_sucursal = bool(getattr(settings, "RESERVA_SEPARACION_POR_SUCURSAL", True))

                        win_ini = fecha - timedelta(minutes=sep_min)
                        win_fin = fecha + timedelta(minutes=sep_min)

                        filtro = Q(cliente=cliente, estado__in=["PEND", "CONF"], fecha__gte=win_ini, fecha__lte=win_fin)
                        if por_sucursal:
                            filtro &= Q(mesa__sucursal=mesa.sucursal)

                        pegadas = Reserva.objects.filter(filtro).order_by("fecha")
                        if pegadas.exists():
                            mas_cercana = min(pegadas, key=lambda r: abs((r.fecha - fecha).total_seconds()))
                            hora_existente = mas_cercana.fecha.astimezone(tz).strftime("%H:%M")
                            url_mis = reverse("reservas:mis_reservas")
                            messages.warning(
                                request,
                                mark_safe(
                                    f"Debes dejar al menos <b>{sep_min//60} horas</b> entre reservas. "
                                    f"Ya tienes una cercana a las <b>{hora_existente}</b>. "
                                    f"<a href='{url_mis}'>Ver mis reservas</a>"
                                )
                            )
                            return redirect("reservas:mis_reservas")

                    reserva = form.save(commit=False)
                    reserva.cliente = cliente
                    reserva.mesa = mesa
                    reserva.estado = "PEND"
                    reserva.fecha = fecha

                    asist_raw = (
                        form.cleaned_data.get("num_personas")
                        or form.cleaned_data.get("asistentes")
                        or form.cleaned_data.get("personas")
                        or request.POST.get("num_personas")
                        or request.POST.get("asistentes")
                        or request.POST.get("personas")
                        or 1
                    )
                    try:
                        asist = int(asist_raw)
                    except (TypeError, ValueError):
                        asist = 1
                    if asist < 1:
                        asist = 1
                    cap_mesa = getattr(mesa, "capacidad", None)
                    if cap_mesa and asist > cap_mesa:
                        asist = cap_mesa
                    reserva.num_personas = asist

                    reserva.full_clean()
                    reserva.save()

                    if not cliente.email and request.user.email:
                        cliente.email = request.user.email
                        cliente.save(update_fields=["email"])

                    def _send_mail():
                        try:
                            enviar_correo_reserva_confirmada(reserva, bcc_sucursal=True)
                        except Exception as e:
                            logger.exception("Fallo al enviar confirmación (reserva=%s): %s", reserva.id, e)

                    transaction.on_commit(_send_mail)

                return redirect("reservas:reserva_exito", reserva_id=reserva.id)

            except Exception as e:
                messages.error(request, f"❌ No se pudo completar la reservación: {e}")
        else:
            messages.error(request, "❌ Revisa los campos del formulario.")
    else:
        initial = {}
        f = (request.GET.get("fecha") or "").strip()
        h = (request.GET.get("hora") or "").strip()
        if f:
            initial["fecha"] = f if not h else f"{f}T{h}"
        form = ReservaForm(mesa=mesa, cliente=cliente, initial=initial)

    return render(
        request,
        "reservas/reservar.html",
        {"form": form, "mesa": mesa, "fecha_listado": fecha_listado},
    )


@login_required
def reserva_exito(request, reserva_id):
    from django.conf import settings
    from django.utils import timezone, formats
    from .utils import booking_total_minutes

    r = get_object_or_404(
        Reserva.objects.select_related("mesa", "mesa__sucursal", "cliente"),
        id=reserva_id,
        cliente__user=request.user,
    )

    tz = timezone.get_current_timezone()
    dt_loc = timezone.localtime(r.fecha, tz)

    ctx = {
        "reserva": r,
        "tolerancia_min": int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5)),

        # ▼ Campos derivados que el template necesita
        "fecha_txt": formats.date_format(dt_loc.date(), "DATE_FORMAT"),
        "hora_txt": dt_loc.strftime("%H:%M"),
        "duracion_min": booking_total_minutes(dt_loc, r.num_personas or 2),
        "personas": r.num_personas or 1,
        "mesa_num": getattr(r.mesa, "numero", r.mesa_id),

        # Contacto
        "contacto_nombre": getattr(r.cliente, "nombre", "") or "",
        "contacto_email": getattr(r.cliente, "email", "") or "",
        "contacto_tel": getattr(r.cliente, "telefono", "") or getattr(r, "telefono", ""),
        "notas": getattr(r, "notas", ""),
    }
    return render(request, "reservas/reserva_exito.html", ctx)



@login_required
def mis_reservas(request):
    from .utils import _auto_cancel_por_tolerancia
    _auto_cancel_por_tolerancia(minutos=6)

    # ✅ Garantiza que exista el perfil Cliente para el usuario actual
    cliente, _ = Cliente.objects.get_or_create(
        user=request.user,
        defaults={
            "nombre": request.user.get_full_name() or request.user.username,
            "email": request.user.email or "",
            # agrega otros defaults si tu modelo los requiere
        },
    )

    GRACIA_MINUTOS = 5
    ahora = timezone.now()
    corte_gracia = ahora - timedelta(minutes=GRACIA_MINUTOS)

    activa = (Reserva.objects
              .filter(cliente=cliente, fecha__gte=corte_gracia)
              .filter(Q(estado='PEND') | Q(estado='CONF'))
              .order_by('fecha')
              .first())

    pasadas = (Reserva.objects
               .filter(cliente=cliente)
               .exclude(id=getattr(activa, 'id', None))
               .order_by('-fecha')[:3])

    return render(request, 'reservas/mis_reservas.html', {
        'reserva_activa': activa,
        'reservas_pasadas': pasadas,
        'ahora': ahora,
    })


# ===================================================================
# SUCURSAL y MESAS (cliente)
# ===================================================================
# reservas/views.py
@staff_member_required
def ver_mesas(request, sucursal_id):
    from .utils import _auto_cancel_por_tolerancia
    from .utils import booking_total_minutes
    _auto_cancel_por_tolerancia(minutos=6)

    sucursal = get_object_or_404(Sucursal, id=sucursal_id)
    _activate_sucursal_tz(sucursal)  # 👈 clave para que slot_inicio/fin sean locales

    if not _puede_ver_sucursal(request.user, sucursal):
        raise Http404()

    inicio, fin = _slot_consultado(request)  # ideal: que devuelva aware en TZ activa
    estados_ocupan = ["PEND", "CONF"]

    try:
        party = int((request.GET.get("party") or "2").strip())
    except Exception:
        party = 2

    total_min = booking_total_minutes(inicio, party)
    mesas_qs = Mesa.objects.filter(sucursal=sucursal)

    reservas_existe = (
        Reserva.objects
        .filter(mesa=OuterRef("pk"), estado__in=estados_ocupan, fecha__lt=fin)
        .annotate(fin_res=Case(default=Value(0), output_field=BooleanField()))
        .filter(fecha__gt=inicio - timedelta(minutes=total_min))
    )

    mesas = (
        mesas_qs
        .annotate(ocupada=Exists(reservas_existe))
        .annotate(disponible=Case(When(ocupada=True, then=Value(False)), default=Value(True), output_field=BooleanField()))
        .order_by("numero", "id")
    )

    ctx = {"sucursal": sucursal, "mesas": mesas, "slot_inicio": inicio, "slot_fin": fin}
    resp = render(request, "reservas/ver_mesas.html", ctx)
    # (opcional) dj_tz.deactivate()
    return resp

# ===================================================================
# ADMIN: SUCURSALES (UI propia) + FORM crear/editar con imagen
# ===================================================================




@staff_member_required
def admin_sucursal_form(request, pk=None):
    """
    Crear o editar una Sucursal desde UI de staff (maneja ImageField si existe).
    - GET: muestra formulario
    - POST: valida y guarda
    Rutas:
      /staff/sucursales/nueva/           -> crear (pk=None)
      /staff/sucursales/<int:pk>/editar/ -> editar
    """
    if pk:
        sucursal = get_object_or_404(Sucursal, pk=pk)
        titulo = "Editar sucursal"
        if not (request.user.is_superuser or _puede_ver_sucursal(request.user, sucursal)):
            return HttpResponseForbidden("No tienes permiso sobre esta sucursal.")
    else:
        sucursal = None
        titulo = "Nueva sucursal"

    if request.method == "POST":
        form = SucursalForm(request.POST, request.FILES, instance=sucursal)
        if form.is_valid():
            obj = form.save()
            # opcional: agregar al staff como administrador de esa sucursal
            if request.user.is_staff and not obj.administradores.filter(id=request.user.id).exists():
                obj.administradores.add(request.user)
            messages.success(request, "✅ Sucursal guardada correctamente.")
            return redirect("reservas:admin_sucursales")
        messages.error(request, "Revisa los campos del formulario.")
    else:
        form = SucursalForm(instance=sucursal)

    return render(request, "reservas/admin_sucursal_form.html", {
        "form": form,
        "titulo": titulo,
        "sucursal": sucursal,
        "csrf_token": get_token(request),
    })


# ===================================================================
# ADMIN: MAPA/DETALLE/CONFIRMAR/AGENDA
# ===================================================================
@staff_member_required
def admin_mapa_sucursal(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
    if not _puede_ver_sucursal(request.user, sucursal):
        return HttpResponseForbidden("No tienes permiso para esta sucursal.")

    # ventana para “estado actual”
    ahora = timezone.now()
    tol_min = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ventana_ini = ahora - timedelta(minutes=tol_min)
    ventana_fin = ahora + timedelta(minutes=tol_min)

    # prefetch simple
    mesas = (
        Mesa.objects.filter(sucursal=sucursal)
        .order_by("numero", "id")
    )

    estado_mesas = []
    for m in mesas:
        # reservas relevantes (hoy +- un margen)
        reservas = list(
            Reserva.objects
            .filter(sucursal=sucursal, mesa=m, fecha__date=ahora.date())
            .order_by("fecha")[:5]
        )

        # estado: bloqueada / reservada (en ventana) / ocupada (si llegó) / disponible
        if m.bloqueada:
            est = "OCUPADA"
        else:
            r_actual = next((r for r in reservas if ventana_ini <= r.fecha <= ventana_fin), None)
            if r_actual and r_actual.llego:
                est = "OCUPADA"
            elif r_actual:
                est = "RESERVADA"
            else:
                est = "DISPONIBLE"

        estado_mesas.append({"mesa": m, "estado": est, "reservas": reservas})

    ctx = {
        "sucursal": sucursal,
        "estado_mesas": estado_mesas,
    }
    return render(request, "reservas/admin_mapa_sucursal.html", ctx)




def _is_chain_owner(user):
    """Devuelve True si el usuario es superuser o tiene el permiso de dueño de cadena."""
    return getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches")




@staff_member_required
def admin_mesa_detalle(request, mesa_id):
    """
    Vista de detalle de mesa (panel staff/admin).

    - Dueño de cadena (superuser o con permiso manage_branches) puede ver todas.
    - Staff solo puede ver mesas de sus sucursales visibles.
    - Muestra la reserva activa o próxima, y habilita acciones de confirmar/finalizar.
    """
    mesa = get_object_or_404(Mesa.objects.select_related("sucursal"), pk=mesa_id)
    if not _puede_ver_sucursal(request.user, mesa.sucursal):
        return HttpResponseForbidden("No tienes permiso para ver esta mesa.")

    # Configuración de tolerancia para llegada (CHECKIN)
    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    gracia = int(getattr(settings, "CHECKIN_GRACIA_MIN", tol))
    ahora = timezone.now()


    reserva = (
        Reserva.objects.filter(
            mesa=mesa,
            estado__in=[Reserva.PEND, Reserva.CONF],
            fecha__gte=ahora - timedelta(minutes=gracia),
        )
        .order_by("fecha")
        .first()
    )
    if not reserva:
        reserva = (
            Reserva.objects.filter(
                mesa=mesa,
                estado__in=[Reserva.PEND, Reserva.CONF],
                fecha__gte=ahora,
            )
            .order_by("fecha")
            .first()
        )

    # Determinar permisos de acción sobre la reserva
    puede_confirmar = False
    puede_finalizar = False

    if reserva:
        inicio = reserva.fecha - timedelta(minutes=tol)
        fin = reserva.fecha + timedelta(minutes=tol)

        puede_confirmar = (
            (not getattr(reserva, "llego", False))
            and (reserva.estado in [Reserva.PEND, Reserva.CONF])
            and (inicio <= ahora <= fin)
        )
        
        puede_finalizar = bool(getattr(reserva, "llego", False))

    # Contexto para template
    ctx = {
        "mesa": mesa,
        "reserva": reserva,
        "puede_confirmar": puede_confirmar,
        "puede_finalizar": puede_finalizar,
    }
    return render(request, "reservas/admin_mesa_detalle.html", ctx)

#####################################################################
@require_POST
@staff_member_required
@transaction.atomic
def admin_confirmar_llegada(request, reserva_id):
    """
    Confirma llegada (check-in) de una reserva con:
    - bloqueo select_for_update
    - validación de tolerancia de tiempo
    - validación de permisos por sucursal
    - opción 'force' solo para superuser
    """
    r = get_object_or_404(Reserva.objects.select_for_update(), pk=reserva_id)

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        return HttpResponseForbidden("No tienes permiso para confirmar esta reserva.")

    if getattr(r, "llego", False):
        messages.info(request, "La llegada ya estaba confirmada.")
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    if r.estado not in [Reserva.PEND, Reserva.CONF]:
        messages.error(request, "La reserva no está en un estado válido para check-in.")
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ahora = timezone.now()
    inicio = r.fecha - timedelta(minutes=tol)
    fin    = r.fecha + timedelta(minutes=tol)

    force = bool(request.POST.get("force")) and request.user.is_superuser
    if not (inicio <= ahora <= fin) and not force:
        messages.error(request, "Fuera de la ventana de llegada.")
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    r.llego = True
    if hasattr(r, "checkin_at"):
        r.checkin_at = ahora
    else:
        setattr(r, "arrived_at", ahora)
    if r.estado == Reserva.PEND:
        r.estado = Reserva.CONF

    update_fields = ["llego", "estado"]
    if hasattr(r, "checkin_at"):
        update_fields.append("checkin_at")
    else:
        update_fields.append("arrived_at")
    if hasattr(r, "modificado"):
        update_fields.append("modificado")

    r.save(update_fields=update_fields)
    messages.success(request, "Llegada confirmada ✅")
    return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)








#####################################################################

# ===================================================================
# DISPONIBILIDAD (cliente y staff) / AGENDA
# ===================================================================
@require_GET
@login_required
def disponibilidad_mesa(request, mesa_id):
    """
    Devuelve JSON con horarios disponibles para una mesa en un día (cliente).
    Usa duración dinámica y fin efectivo (respeta liberada_en) para choques.
    """
    from .utils import anticipacion_minima_para, booking_total_minutes
    if not _en_ventana_debug_o_ajax(request):
        return HttpResponseForbidden("Sólo AJAX")

    mesa = get_object_or_404(Mesa, pk=mesa_id)
    dia = _parse_fecha_param(request.GET.get("fecha"))

    # party opcional (default 2)
    try:
        party = int((request.GET.get("party") or "2").strip())
    except Exception:
        party = 2

    tz = timezone.get_current_timezone()
    hoy_local = timezone.localdate()

    apertura = int(getattr(settings, "HORARIO_APERTURA", 8))
    cierre   = int(getattr(settings, "HORARIO_CIERRE", 22))
    paso     = 15

    inicio_jornada = timezone.make_aware(datetime(dia.year, dia.month, dia.day, apertura, 0), tz)
    fin_jornada    = timezone.make_aware(datetime(dia.year, dia.month, dia.day, cierre,   0), tz)

    # Necesitamos fecha, num_personas y liberada_en para calcular fin_efectivo
    reservas = (
        Reserva.objects
        .filter(mesa=mesa, estado__in=["PEND", "CONF"])
        .filter(fecha__lt=fin_jornada)
        .only("fecha", "num_personas", "liberada_en")
        .order_by("fecha")
    )

    bloqueos = (
        BloqueoMesa.objects
        .filter(sucursal=mesa.sucursal)
        .filter(Q(mesa__isnull=True) | Q(mesa=mesa))
        .filter(Q(inicio__lt=fin_jornada) & Q(fin__gt=inicio_jornada))
        .only("inicio", "fin")
    )

    def se_traslapa(ini_a, fin_a, ini_b, fin_b):
        return ini_a < fin_b and fin_a > ini_b

    def ocupado(slot_ini, slot_fin):
        # Reservas: usar fin EFECTIVO (respeta liberada_en)
        for r in reservas:
            r_ini = r.fecha
            r_fin = r.fin_efectivo(getattr(r, "num_personas", party) or party)
            if se_traslapa(slot_ini, slot_fin, r_ini, r_fin):
                return True
        # Bloqueos
        for b in bloqueos:
            if se_traslapa(slot_ini, slot_fin, b.inicio, b.fin):
                return True
        return False

    now_local = timezone.localtime()
    slots = []
    t = inicio_jornada
    while t < fin_jornada:
        dur_min = booking_total_minutes(t, party)
        if t + timedelta(minutes=dur_min) > fin_jornada:
            break

        # oculta pasado y respeta anticipación
        if dia == hoy_local and t < now_local:
            t += timedelta(minutes=paso); continue
        antic_min = anticipacion_minima_para(t)
        if t < now_local + timedelta(minutes=antic_min):
            t += timedelta(minutes=paso); continue

        slot_ini = t
        slot_fin = t + timedelta(minutes=dur_min)
        if not ocupado(slot_ini, slot_fin):
            slots.append(t.strftime("%H:%M"))

        t += timedelta(minutes=paso)

    return JsonResponse({
        "mesa": mesa_id,
        "fecha": dia.isoformat(),
        "duracion_min": booking_total_minutes(inicio_jornada, party),
        "slots": slots,
    })



# Alias opcional si en tus urls usas disponibilidad_mesa_json
disponibilidad_mesa_json = disponibilidad_mesa

@require_GET
@user_passes_test(lambda u: u.is_staff or u.is_superuser)
def agenda_mesa(request, mesa_id):
    if not _en_ventana_debug_o_ajax(request):
        return HttpResponseForbidden("Sólo AJAX")
    try:
        mesa = Mesa.objects.get(pk=mesa_id)
    except Mesa.DoesNotExist:
        return JsonResponse({"error": "Mesa no existe"}, status=404)

    fecha_qs = request.GET.get("fecha")
    dia = _parse_fecha_param(fecha_qs)

    tz = timezone.get_current_timezone()
    inicio = timezone.make_aware(datetime(dia.year, dia.month, dia.day, 0, 0), tz)
    fin = inicio + timedelta(days=1)

    reservas = (
        Reserva.objects
        .filter(mesa=mesa, fecha__gte=inicio, fecha__lt=fin)
        .only("fecha", "num_personas", "liberada_en", "estado", "cliente")
        .order_by("fecha")
    )

    items = []
    for r in reservas:
        fin_eff = r.fin_efectivo(getattr(r, "num_personas", 2) or 2)
        items.append({
            "id": r.id,
            "estado": r.estado,
            "inicio": r.fecha.astimezone(tz).strftime("%H:%M"),
            "fin":  fin_eff.astimezone(tz).strftime("%H:%M"),
            "cliente": getattr(r.cliente, "nombre", ""),
        })

    return JsonResponse({"items": items})



# ===================================================================
# ADMIN: BUSCAR/CHECK-IN/CANCELAR/REACTIVAR por FOLIO
# ===================================================================

@login_required
def admin_buscar_folio(request):
    if not request.user.is_staff:
        return redirect("reservas:home")

    folio = (request.GET.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    reserva = None
    error = None
    puede_confirmar = False
    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ventana_ini = ventana_fin = None

    if folio:
        try:
            reserva = (Reserva.objects
                       .select_related("mesa__sucursal", "cliente")
                       .get(folio=folio))

            ahora = timezone.now()
            inicio = reserva.fecha - timedelta(minutes=tol)
            fin    = reserva.fecha + timedelta(minutes=tol)

            puede_confirmar = (
                (not getattr(reserva, "llego", False)) and
                (reserva.estado in ["PEND", "CONF"]) and
                (inicio <= ahora <= fin)
            )

            tz = timezone.get_current_timezone()
            ventana_ini = inicio.astimezone(tz).strftime("%d/%b/%Y %H:%M")
            ventana_fin = fin.astimezone(tz).strftime("%d/%b/%Y %H:%M")

        except Reserva.DoesNotExist:
            error = f"No se encontró ninguna reserva con el folio {folio}."

    ctx = {
        "folio": folio,
        "reserva": reserva,
        "error": error,
        "puede_confirmar": puede_confirmar,
        "tolerancia_min": tol,
        "ventana_ini": ventana_ini,
        "ventana_fin": ventana_fin,
    }
    return render(request, "reservas/admin_buscar_folio.html", ctx)


@staff_member_required
def admin_checkin_por_folio(request):
    if request.method != "POST":
        return redirect("reservas:admin_buscar_folio")

    folio = (request.POST.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    try:
        r = Reserva.objects.get(folio=folio)
    except Reserva.DoesNotExist:
        messages.error(request, "No se encontró la reserva.")
        return redirect("reservas:admin_buscar_folio")

    tol = int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5))
    ahora = timezone.now()
    inicio = r.fecha - timedelta(minutes=tol)
    fin    = r.fecha + timedelta(minutes=tol)

    force = bool(request.POST.get("force")) and request.user.is_superuser

    if getattr(r, "llego", False):
        messages.warning(request, "Esta reserva ya fue marcada como llegada.")
    elif r.estado not in ["PEND", "CONF"]:
        messages.error(request, "La reserva no está en un estado válido para check-in.")
    elif not (inicio <= ahora <= fin) and not force:
        messages.error(request, "Fuera de la ventana de llegada.")
    else:
        r.llego = True
        if hasattr(r, "checkin_at"):
            r.checkin_at = ahora
        else:
            setattr(r, "arrived_at", ahora)
        if r.estado != "CONF":
            r.estado = "CONF"

        update_fields = ["llego", "estado"]
        if hasattr(r, "checkin_at"):
            update_fields.append("checkin_at")
        else:
            update_fields.append("arrived_at")
        if hasattr(r, "modificado"):
            update_fields.append("modificado")

        r.save(update_fields=update_fields)
        messages.success(request, f"✅ Llegada confirmada para folio {r.folio}.")

    return HttpResponseRedirect(f"{reverse('reservas:admin_buscar_folio')}?folio={folio}")


@staff_member_required
@require_POST
def admin_cancelar_por_folio(request):
    folio = (request.POST.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    try:
        r = Reserva.objects.select_related("mesa__sucursal").get(folio=folio)
    except Reserva.DoesNotExist:
        messages.error(request, "No se encontró la reserva.")
        return redirect("reservas:admin_buscar_folio")

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        messages.error(request, "No tienes permiso para cancelar esta reserva.")
        return HttpResponseRedirect(f"{reverse('reservas:admin_buscar_folio')}?folio={folio}")

    if r.estado == "CANC":
        messages.info(request, f"La reserva {r.folio} ya estaba cancelada.")
    else:
        r.estado = "CANC"
        r.save(update_fields=["estado"])
        messages.success(request, f"✅ Reserva {r.folio} cancelada correctamente.")

    return HttpResponseRedirect(f"{reverse('reservas:admin_buscar_folio')}?folio={folio}")


@staff_member_required
@require_POST
def admin_reactivar_por_folio(request):
    folio = (request.POST.get("folio") or "").strip().upper()
    if folio and not folio.startswith("R-"):
        folio = "R-" + folio.lstrip("R").lstrip("-").strip()

    try:
        r = Reserva.objects.select_related("mesa__sucursal").get(folio=folio)
    except Reserva.DoesNotExist:
        messages.error(request, "No se encontró la reserva.")
        return HttpResponseRedirect(reverse("reservas:admin_dashboard"))

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        messages.error(request, "No tienes permiso sobre esta sucursal.")
        return HttpResponseRedirect(reverse("reservas:admin_dashboard"))

    if r.estado != "CANC":
        messages.info(request, f"La reserva {r.folio} no está cancelada.")
    else:
        r.estado = "PEND"
        r.save(update_fields=["estado"])
        messages.success(request, f"✅ Reserva {r.folio} reactivada como {r.get_estado_display()}.")

    fecha = request.GET.get("fecha")
    url = reverse("reservas:admin_dashboard")
    return HttpResponseRedirect(f"{url}?fecha={fecha}" if fecha else url)


# ===================================================================
# ADMIN: DASHBOARD y WALK-IN
# ===================================================================

@staff_member_required
def admin_dashboard(request):
    tz = timezone.get_current_timezone()
    fecha_q = (request.GET.get("fecha") or "").strip()
    try:
        dia = datetime.strptime(fecha_q, "%Y-%m-%d").date() if fecha_q else timezone.localdate()
    except Exception:
        dia = timezone.localdate()

    inicio = timezone.make_aware(datetime(dia.year, dia.month, dia.day, 0, 0), tz)
    fin    = inicio + timezone.timedelta(days=1)

    if request.user.is_superuser:
        filtro_sucursal = {}
    else:
        try:
            perfil = PerfilAdmin.objects.get(user=request.user)
            filtro_sucursal = {"mesa__sucursal_id": perfil.sucursal_asignada_id}
        except PerfilAdmin.DoesNotExist:
            filtro_sucursal = {"mesa__sucursal_id__isnull": True}

    reservas = (
        Reserva.objects
        .select_related("cliente", "mesa__sucursal")
        .filter(fecha__gte=inicio, fecha__lt=fin, **filtro_sucursal)
        .order_by("fecha")
    )

    return render(request, "reservas/admin_dashboard.html", {"reservas": reservas, "hoy": dia})

@staff_member_required
def admin_walkin_reserva(request):
    """
    Crea una reserva Walk-in, opcionalmente fijando sucursal del PerfilAdmin.
    """
    suc_pref = None
    if not request.user.is_superuser:
        try:
            suc_pref = PerfilAdmin.objects.get(user=request.user).sucursal_asignada
        except PerfilAdmin.DoesNotExist:
            suc_pref = None

    if request.method == "POST":
        form = WalkInReservaForm(request.POST, user=request.user, sucursal_pref=suc_pref)
        if form.is_valid():
            reserva = form.save()
            tz = timezone.get_current_timezone()
            dia = timezone.localdate(reserva.fecha, tz).isoformat()
            messages.success(
                request,
                mark_safe(
                    f"✅ Walk-in creada para <b>{reserva.cliente.nombre}</b> "
                    f"({timezone.localtime(reserva.fecha, tz):%d/%b %H:%M}). "
                    f"Folio: <b>{reserva.folio}</b>"
                ),
            )
            url = reverse("reservas:admin_dashboard")
            return redirect(f"{url}?fecha={dia}")
        messages.error(request, "Revisa los campos del formulario.")
    else:
        form = WalkInReservaForm(user=request.user, sucursal_pref=suc_pref)

    return render(request, "reservas/admin_walkin_form.html", {"form": form})
# ===================================================================
# API Staff: mesas y bloqueos (JSON)
# ===================================================================

def _json_bad(msg, status=400):
    return JsonResponse({"ok": False, "error": msg}, status=status)


@staff_member_required
@require_POST
def admin_api_mesa_create(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return _json_bad("JSON inválido")

    sucursal_id = data.get("sucursal_id")
    numero      = data.get("numero")
    capacidad   = data.get("capacidad")
    ubicacion   = data.get("ubicacion","")
    bloqueada   = bool(data.get("bloqueada", False))

    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)

    if not numero:
        return _json_bad("Falta 'numero'.")
    if not capacidad:
        return _json_bad("Falta 'capacidad'.")

    try:
        capacidad = int(capacidad)
        if capacidad <= 0:
            raise ValueError
    except ValueError:
        return _json_bad("Capacidad debe ser entero > 0.")

    m = Mesa.objects.create(
        sucursal=sucursal,
        numero=numero,
        capacidad=capacidad,
        ubicacion=ubicacion or "",
        bloqueada=bloqueada if hasattr(Mesa, "bloqueada") else False,
    )
    return JsonResponse({"ok": True, "mesa": {
        "id": m.id, "numero": m.numero, "capacidad": m.capacidad,
        "ubicacion": getattr(m, "ubicacion", "") or "",
        "bloqueada": getattr(m, "bloqueada", False),
    }})


def _slots_disponibles(mesa, fecha_dt, party=2):
    """
    Devuelve lista de datetimes (aware) con inicios posibles para ese día,
    considerando la duración dinámica, choques con reservas (con fin efectivo)
    y bloqueos. Usa paso de 15 minutos.
    """
    from .utils import booking_total_minutes  # asegúrate de tener esta función en utils

    if hasattr(mesa, "bloqueada") and getattr(mesa, "bloqueada", False):
        return []

    tz = ZoneInfo(mesa.sucursal.timezone)
    base = timezone.make_aware(datetime(fecha_dt.year, fecha_dt.month, fecha_dt.day, 0, 0, 0), tz)

    apertura = int(getattr(settings, 'HORARIO_APERTURA', 8))
    cierre   = int(getattr(settings, 'HORARIO_CIERRE', 22))
    paso     = 15

    inicio_j = base + timedelta(hours=apertura)
    fin_j    = base + timedelta(hours=cierre)

    # Cargar reservas del rango del día (un poco más amplio) y bloqueos
    # Importante: no uses .only('fecha') a secas; necesitamos num_personas y liberada_en
    reservas = (
        Reserva.objects
        .filter(
            mesa=mesa,
            estado__in=['PEND', 'CONF'],
            fecha__gte=inicio_j - timedelta(hours=3),
            fecha__lt=fin_j + timedelta(hours=3),
        )
        .only('fecha', 'num_personas', 'liberada_en')  # evita queries extra al calcular fin_efectivo
        .order_by('fecha')
    )

    bloqueos = (
        BloqueoMesa.objects
        .filter(sucursal=mesa.sucursal)
        .filter(Q(mesa__isnull=True) | Q(mesa=mesa))
        .filter(Q(inicio__lt=fin_j) & Q(fin__gt=inicio_j))
        .only('inicio', 'fin')
    )

    def se_traslapa(ini_a, fin_a, ini_b, fin_b):
        return ini_a < fin_b and fin_a > ini_b

    def esta_libre(slot_ini):
        # duración dinámica del slot propuesto (depende de hora y tamaño de grupo)
        total_min = booking_total_minutes(slot_ini, party)
        slot_fin = slot_ini + timedelta(minutes=total_min)

        # Reservas: usar fin EFECTIVO (respeta liberada_en)
        for r in reservas:
            r_ini = r.fecha
            r_fin = r.fin_efectivo(getattr(r, "num_personas", party) or party)
            if se_traslapa(slot_ini, slot_fin, r_ini, r_fin):
                return False

        # Bloqueos
        for b in bloqueos:
            if se_traslapa(slot_ini, slot_fin, b.inicio, b.fin):
                return False

        return True

    out = []
    cur = inicio_j
    ahora = timezone.localtime()
    while cur < fin_j:
        dur_min = booking_total_minutes(cur, party)
        if cur + timedelta(minutes=dur_min) > fin_j:
            break
        if cur >= ahora and esta_libre(cur):
            out.append(cur)
        cur += timedelta(minutes=paso)

    return out






@staff_member_required
@require_http_methods(["POST"])
def admin_api_bloqueo_create(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    sucursal = get_object_or_404(Sucursal, pk=data.get("sucursal_id"))

    if not _puede_ver_sucursal(request.user, sucursal):
        return JsonResponse({"ok": False, "error": "Sin permiso sobre la sucursal."}, status=403)

    mesa = None
    mesa_id = data.get("mesa_id")
    if mesa_id:
        mesa = get_object_or_404(Mesa, pk=mesa_id, sucursal=sucursal)

    inicio = parse_datetime(data.get("inicio") or "")
    fin    = parse_datetime(data.get("fin") or "")
    if not inicio or not fin:
        return JsonResponse({"ok": False, "error": "Fechas 'inicio' y 'fin' requeridas (ISO 8601)."}, status=400)
    if fin <= inicio:
        return JsonResponse({"ok": False, "error": "El fin debe ser mayor al inicio."}, status=400)

    tz = timezone.get_current_timezone()
    if timezone.is_naive(inicio):
        inicio = timezone.make_aware(inicio, tz)
    if timezone.is_naive(fin):
        fin = timezone.make_aware(fin, tz)

    mot = (data.get("motivo") or "").strip()[:200]

    try:
        b = BloqueoMesa.objects.create(
            sucursal=sucursal, mesa=mesa, inicio=inicio, fin=fin, motivo=mot,
        )
    except TypeError as e:
        return JsonResponse({"ok": False, "error": f"Error al crear bloqueo: {e}"}, status=500)

    return JsonResponse({"ok": True, "bloqueo": {
        "id": b.id, "mesa_id": b.mesa_id, "sucursal_id": b.sucursal_id,
        "inicio": b.inicio.isoformat(), "fin": b.fin.isoformat(), "motivo": b.motivo,
    }})


@staff_member_required
@require_http_methods(["GET"])
def admin_api_bloqueo_list(request):
    """
    Lista bloqueos en JSON.
    Querystring:
      - sucursal_id (int) [requerido]
      - mesa_id (int|opcional)
      - desde (YYYY-MM-DD|opcional, por defecto hoy local)
    """
    try:
        sucursal_id = int(request.GET.get("sucursal_id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "sucursal_id requerido"}, status=400)

    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
    if not _puede_ver_sucursal(request.user, sucursal):
        return JsonResponse({"ok": False, "error": "Sin permiso sobre la sucursal"}, status=403)

    mesa_id = request.GET.get("mesa_id")
    mesa = None
    if mesa_id:
        try:
            mesa_id = int(mesa_id)
            mesa = get_object_or_404(Mesa, pk=mesa_id, sucursal=sucursal)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "mesa_id inválido"}, status=400)

    try:
        dstr = request.GET.get("desde", "") or timezone.localdate().isoformat()
        y_, m_, d_ = [int(x) for x in dstr.split("-")]
        desde = timezone.make_aware(datetime(y_, m_, d_, 0, 0), timezone.get_current_timezone())
    except Exception:
        return JsonResponse({"ok": False, "error": "desde inválido (YYYY-MM-DD)"}, status=400)

    qs = BloqueoMesa.objects.filter(sucursal=sucursal, fin__gte=desde)
    if mesa:
        qs = qs.filter(Q(mesa__isnull=True) | Q(mesa=mesa))
    qs = qs.order_by("inicio")[:200]

    items = []
    for b in qs:
        items.append({
            "id": b.id,
            "sucursal_id": b.sucursal_id,
            "mesa_id": b.mesa_id,
            "inicio": b.inicio.isoformat(),
            "fin": b.fin.isoformat(),
            "motivo": b.motivo or "",
            "scope": "mesa" if b.mesa_id else "sucursal",
        })
    return JsonResponse({"ok": True, "items": items})


@staff_member_required
@require_http_methods(["POST"])
def admin_api_bloqueo_delete(request):
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "JSON inválido"}, status=400)

    try:
        bid = int(data.get("id"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "id requerido"}, status=400)

    b = get_object_or_404(BloqueoMesa, pk=bid)
    if not _puede_ver_sucursal(request.user, b.sucursal):
        return JsonResponse({"ok": False, "error": "Sin permiso"}, status=403)

    b.delete()
    return JsonResponse({"ok": True, "deleted": bid})


# ===================================================================
# Utilidades menores / navegación
# ===================================================================

def alguna_vista_que_redirige_a_login(request):
    storage = get_messages(request)
    for _ in storage:
        pass
    return redirect("account_login")


def valida_separacion_minima(cliente, mesa, fecha, es_staff=False):
    if es_staff:
        return None
    sep_min = int(getattr(settings, "RESERVA_MIN_SEPARACION_MIN", 120))
    por_sucursal = bool(getattr(settings, "RESERVA_SEPARACION_POR_SUCURSAL", True))
    win_ini, win_fin = fecha - timedelta(minutes=sep_min), fecha + timedelta(minutes=sep_min)
    filtro = Q(cliente=cliente, estado__in=["PEND", "CONF"], fecha__gte=win_ini, fecha__lte=win_fin)
    if por_sucursal:
        filtro &= Q(mesa__sucursal=mesa.sucursal)
    return (Reserva.objects.filter(filtro).order_by("fecha").first())


def _redir_despues_confirmar(request, reserva):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url:
        return redirect(next_url)
    if request.user.is_staff:
        return redirect("reservas:admin_mesa_detalle", mesa_id=reserva.mesa_id)
    return redirect("reservas:mis_reservas")


@login_required
@permission_required("reservas.change_reserva", raise_exception=True)
def confirmar_reserva(request, reserva_id):
    """
    Marca una reserva como CONF y envía correo de confirmación.
    Requiere permiso change_reserva (staff).
    """
    reserva = get_object_or_404(Reserva, id=reserva_id)

    if reserva.estado == Reserva.CONF:
        messages.info(request, "La reserva ya estaba confirmada.")
        return _redir_despues_confirmar(request, reserva)

    reserva.estado = Reserva.CONF
    reserva.save(update_fields=["estado"])

    try:
        enviar_correo_reserva_confirmada(reserva, bcc_sucursal=True)
        messages.success(request, "Reserva confirmada y correo enviado al cliente ✅")
    except Exception as e:
        messages.warning(request, f"Reserva confirmada, pero el correo no se pudo enviar: {e}")

    return _redir_despues_confirmar(request, reserva)


# ===================================================================
# STAFF: LISTA DE RESERVAS
# ===================================================================

@staff_member_required
def admin_reservas(request):
    """
    Lista de reservas para staff. Si es superuser ve todas; si es staff normal,
    filtra por su sucursal asignada. GET ?q=<folio>
    """
    from .utils import _auto_cancel_por_tolerancia
    _auto_cancel_por_tolerancia(minutos=6)

    q = (request.GET.get("q") or "").strip()

    if request.user.is_superuser:
        reservaciones = Reserva.objects.select_related("cliente", "mesa__sucursal")
    else:
        try:
            perfil = PerfilAdmin.objects.get(user=request.user)
            reservaciones = (
                Reserva.objects.select_related("cliente", "mesa__sucursal")
                .filter(mesa__sucursal=perfil.sucursal_asignada)
            )
        except PerfilAdmin.DoesNotExist:
            reservaciones = Reserva.objects.none()

    if q:
        reservaciones = reservaciones.filter(folio__icontains=q)

    reservaciones = reservaciones.order_by("-fecha")
    return render(request, "reservas/admin/reservas.html", {"reservas": reservas})


# --- Compat: endpoint antiguo /staff/api/disponibilidad/?mesa_id=... ---
@staff_member_required
@require_GET
def staff_disponibilidad_json(request):
    """
    Proxy compatible con la URL antigua.
    Parámetros:
      - mesa_id (int) [requerido]
      - fecha=YYYY-MM-DD (opcional)
    Devuelve el mismo JSON que admin_disponibilidad_mesa.
    """
    mesa_id = request.GET.get("mesa_id")
    if not mesa_id:
        return JsonResponse({"ok": False, "error": "mesa_id requerido"}, status=400)
    try:
        mesa_id = int(mesa_id)
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "mesa_id inválido"}, status=400)

    # Reutilizamos la lógica existente
    return admin_disponibilidad_mesa(request, mesa_id)



@staff_member_required
def admin_site_sucursales(request):
    return redirect("admin:reservas_sucursal_changelist")

@staff_member_required
def admin_site_mesas(request):
    return redirect("admin:reservas_mesa_changelist")

@staff_member_required
def admin_site_reservas(request):
    return redirect("admin:reservas_reserva_changelist")


# --- API: actualizar mesa (JSON) ---

# ---- API: actualizar mesa (incluye posiciones del canvas) ----
@staff_member_required
def admin_api_mesa_update(request, mesa_id):
    mesa = get_object_or_404(Mesa, pk=mesa_id)
    if request.method == "POST":
        mesa.numero = request.POST.get("numero") or mesa.numero
        mesa.capacidad = request.POST.get("capacidad") or mesa.capacidad
        mesa.ubicacion = request.POST.get("ubicacion") or ""
        mesa.notas = request.POST.get("notas") or ""

        zona = request.POST.get("zona")
        if zona in {"interior", "terraza", "exterior"}:
            mesa.zona = zona

        mesa.save(update_fields=["numero", "capacidad", "ubicacion", "notas", "zona"])
        return JsonResponse({"ok": True})


@staff_member_required
def admin_mesa_crear(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
    assert_user_can_manage_sucursal(request.user, sucursal)  # 🔒

    if request.method == "POST":
        try:
            numero = int(request.POST.get("numero") or 0)
        except (TypeError, ValueError):
            numero = 0

        capacidad = int(request.POST.get("capacidad") or 4)
        zona = request.POST.get("zona") or "interior"

        # Si el número no viene o ya existe, toma el siguiente consecutivo
        if numero <= 0 or Mesa.objects.filter(sucursal=sucursal, numero=numero).exists():
            ultimo = Mesa.objects.filter(sucursal=sucursal).order_by("-numero").first()
            numero = (ultimo.numero + 1) if ultimo else 1

        Mesa.objects.create(
            sucursal=sucursal,
            numero=numero,
            capacidad=capacidad,
            zona=zona,
            ubicacion=request.POST.get("ubicacion") or "",
            notas=request.POST.get("notas") or "",
        )

        messages.success(request, f"Mesa {numero} creada correctamente.")
        return redirect("reservas:admin_mapa_sucursal", sucursal_id=sucursal.id)

    return render(request, "reservas/admin_mesa_form.html", {"sucursal": sucursal})


# reservas/views.py


def _proximos_slots(base_dt, n=3, paso_min=15, tz=None):
    """
    Devuelve N horarios próximos como strings (ej: '7:30 pm'),
    formateados en la TZ indicada (o la activa).
    """
    tz = tz or dj_tz.get_current_timezone()

    start = base_dt.replace(second=0, microsecond=0)
    resto = start.minute % paso_min
    if resto:
        start += timedelta(minutes=paso_min - resto)

    slots = []
    cur = start
    for _ in range(n):
        # Localiza en la TZ deseada
        dt_local = cur.astimezone(tz)
        if os.name == "nt":
            s = dt_local.strftime("%#I:%M %p")
        else:
            s = dt_local.strftime("%-I:%M %p")
        slots.append(s.lower())
        cur += timedelta(minutes=paso_min)
    return slots






@login_required
@staff_member_required

def admin_sucursal_contenido(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, id=sucursal_id)

    # (Opcional) Si quieres restringir a administradores asignados:
    # if not (request.user.is_superuser or request.user in sucursal.administradores.all()):
    #     messages.error(request, "No tienes permiso para editar esta sucursal.")
    #     return redirect("reservas:admin_sucursales")

    if request.method == "POST":
        form = SucursalForm(request.POST, request.FILES, instance=sucursal)
        formset = SucursalFotoFormSet(request.POST, request.FILES, instance=sucursal, prefix="gal")
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Contenido actualizado correctamente.")
            return redirect("reservas:admin_sucursal_contenido", sucursal_id=sucursal.id)
        else:
            messages.error(request, "Revisa los campos marcados.")
    else:
        form = SucursalForm(instance=sucursal)
        formset = SucursalFotoFormSet(instance=sucursal, prefix="gal")

    return render(request, "reservas/admin_sucursal_contenido.html", {
        "sucursal": sucursal,
        "form": form,
        "formset": formset,
    })
 

def sucursales_visibles_qs(user):
    if not user.is_authenticated or not user.is_staff:
        return Sucursal.objects.none()
    if user.is_superuser:
        return Sucursal.objects.all()
    # Si tiene sucursal asignada, forzamos esa
    try:
        perfil = PerfilAdmin.objects.get(user=user)
        if perfil.sucursal_asignada_id:
            return Sucursal.objects.filter(pk=perfil.sucursal_asignada_id, activo=True)
    except PerfilAdmin.DoesNotExist:
        pass
    # Si no hay perfil asignado, caemos a M2M
    return Sucursal.objects.filter(activo=True, administradores=user)




@login_required
def admin_sucursales(request):
    u = request.user

    # 1) Superuser o Dueño de Cadena => ve todas (¡tal cual lo tenías!)
    if u.is_superuser or (u.is_staff and u.has_perm("reservas.manage_branches")):
        sucursales = Sucursal.objects.all().order_by("id")
        return render(request, "reservas/admin_sucursales.html", {"sucursales": sucursales})

    # 2) Admin de sucursal => solo su sucursal asignada (¡tal cual lo tenías!)
    perfil = PerfilAdmin.objects.filter(user=u).select_related("sucursal_asignada").first()
    if perfil and perfil.sucursal_asignada_id:
        sucursales = Sucursal.objects.filter(pk=perfil.sucursal_asignada_id).order_by("id")
        return render(request, "reservas/admin_sucursales.html", {"sucursales": sucursales})

    # 3) NUEVO: admins por país (CountryAdminScope / perfil.paises) y/o M2M 'administradores'
    #    Usa el queryset con reglas completas que ya implementamos en SucursalQuerySet.for_user().
    sucursales = Sucursal.objects.for_user(u).order_by("id")
    if sucursales.exists():
        return render(request, "reservas/admin_sucursales.html", {"sucursales": sucursales})

    # 4) Sin nada visible
    messages.info(request, "No tienes sucursal asignada.")
    return render(request, "reservas/admin_sucursales.html", {"sucursales": []})


def sucursal_detalle(request, slug):
    s = get_object_or_404(Sucursal.objects.filter(activo=True), slug=slug)

    # 🔑 Activar TZ local de la sucursal
    tz = ZoneInfo(s.timezone)
    dj_tz.activate(tz)

    date_str = request.GET.get("date")
    time_str = request.GET.get("time")
    party = (request.GET.get("party") or "2").strip()

    # now/base_dt en la TZ de la sucursal
    now = dj_tz.localtime()
    try:
        if date_str:
            base_dt = dj_tz.make_aware(
                datetime.strptime(f"{date_str} {time_str or '19:00'}", "%Y-%m-%d %H:%M"),
                tz
            )
        else:
            base_dt = now
    except Exception:
        base_dt = now

    try:
        precio_signos = "$" * int(s.precio_nivel or 1)
    except Exception:
        precio_signos = "$"

    # Sugerencias en la TZ de la sucursal
    proximos = _proximos_slots(base_dt, 5, tz=tz)

    # Menú (categorías + items activos)
    categorias = (s.menu_categorias
                    .prefetch_related("items")
                    .order_by("orden", "id"))

    menu_sections = []
    for c in categorias:
        items = [it for it in c.items.all() if it.activo]
        if items:
            menu_sections.append({"titulo": c.titulo, "items": items})

    # Reseñas (paginadas)
    rev_qs = s.reviews_obj.all()
    page = request.GET.get("page") or 1
    page_obj = Paginator(rev_qs, 6).get_page(page)

    ctx = {
        "s": s,
        "precio_signos": precio_signos,
        "party": party or "2",
        "date": date_str or dj_tz.localdate().strftime("%Y-%m-%d"),
        "time": time_str or "19:00",
        "proximos_slots": proximos,
        "fotos": s.fotos.all(),
        "menu_sections": menu_sections,
        "page_obj": page_obj,   # reseñas
    }
    return render(request, "reservas/sucursal_detalle.html", ctx)



@require_GET
def api_slots_sucursal(request, sucursal_id):
    """
    Devuelve horas disponibles (UNIÓN de mesas libres) para una sucursal.
    Respeta 'party' y 'limit', usa ancla temporal razonable y pasa 'party'
    a _slots_disponibles para evitar inconsistencias.
    Salida (formato plano):
      {
        "sucursal": <id>,
        "fecha": "YYYY-MM-DD",
        "party": <int>,
        "slots": [{"label":"11:45 am","value":"11:45"}, ...],
        "duracion_min": <int>
      }
    """
    # --- utilidades ---
    from .utils import booking_total_minutes, _slots_disponibles
    try:
        from .utils import _parse_fecha_param as _parse_fecha_param_util
    except Exception:
        _parse_fecha_param_util = None

    # ---------- parámetros ----------
    fecha_raw = (request.GET.get("fecha") or request.GET.get("date") or "").strip()

    # party
    try:
        party = int((request.GET.get("party") or "2").strip())
    except Exception:
        party = 2
    party = max(1, party)

    # limit
    try:
        limit = int((request.GET.get("limit") or "12").strip())
    except Exception:
        limit = 12
    limit = max(1, limit)

    # sucursal (activa) y TZ local
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id, activo=True)
    tz = ZoneInfo(sucursal.timezone)
    dj_tz.activate(tz)  # 🔑 todo lo que siga usa la TZ de la sucursal

    # fecha (YYYY-MM-DD)
    if _parse_fecha_param_util:
        dia = _parse_fecha_param_util(fecha_raw)
    else:
        dia = parse_date(fecha_raw) if fecha_raw else None
    if dia is None:
        dia = dj_tz.localdate()  # hoy en la TZ de la sucursal

    now_loc = dj_tz.localtime()  # ahora en TZ sucursal

    # ---------- ancla de tiempo ----------
    # si es hoy, no permitimos ir al pasado; si es otro día, usamos hora de apertura
    hraw = (request.GET.get("hora") or request.GET.get("time") or "").strip().lower()
    anchor = None
    for fmt in ("%H:%M", "%I:%M%p", "%I:%M %p", "%H", "%I%p", "%I %p"):
        try:
            t = datetime.strptime(hraw, fmt).time()
            anchor = dj_tz.make_aware(datetime.combine(dia, t), tz)
            break
        except Exception:
            pass

    if anchor is None:
        if now_loc.date() == dia:
            anchor = now_loc
        else:
            apertura = int(getattr(settings, "HORARIO_APERTURA", 8))
            anchor = dj_tz.make_aware(datetime(dia.year, dia.month, dia.day, apertura, 0), tz)
    else:
        if now_loc.date() == dia and anchor < now_loc:
            anchor = now_loc

    # redondeo del anchor al siguiente múltiplo de intervalo
    step = int(getattr(settings, "RESERVA_INTERVALO_MIN", 15))
    bump = (step - (anchor.minute % step)) % step
    if bump:
        anchor = anchor + timedelta(minutes=bump)

    # ---------- unión de slots por mesa ----------
    mesas = Mesa.objects.filter(sucursal=sucursal, capacidad__gte=party).only("id", "capacidad")
    all_slots = set()

    if not mesas.exists():
        return JsonResponse({
            "sucursal": sucursal.id,
            "fecha": dia.isoformat(),
            "party": party,
            "slots": [],
            "duracion_min": booking_total_minutes(anchor, party),
        })

    # Fallback: soportar firma antigua de _slots_disponibles (sin 'party')
    def _slots_for_mesa(m, dia, party):
        try:
            return _slots_disponibles(m, dia, party=party)
        except TypeError as e:
            if "unexpected keyword argument 'party'" in str(e):
                return _slots_disponibles(m, dia)
            raise

    for m in mesas:
        try:
            for dt in _slots_for_mesa(m, dia, party):
                if dt >= anchor:
                    all_slots.add(dt)
        except Exception:
            continue

    futuros = sorted(all_slots)[:limit]

    # ---------- formateo para UI ----------
    def _label_12h(dloc: datetime) -> str:
        fmt = "%#I:%M %p" if os.name == "nt" else "%-I:%M %p"
        try:
            return dloc.strftime(fmt).lower()
        except Exception:
            return dloc.strftime("%I:%M %p").lstrip("0").lower()

    def _fmt(dt):
        dloc = dt.astimezone(tz)
        return {"label": _label_12h(dloc), "value": dloc.strftime("%H:%M")}

    dur_min = booking_total_minutes(anchor, party)
    payload = [_fmt(dt) for dt in futuros]

    return JsonResponse({
        "sucursal": sucursal.id,
        "fecha": dia.isoformat(),
        "party": party,
        "slots": payload,
        "duracion_min": dur_min,
    })





@staff_member_required
def admin_disponibilidad_mesa(request, mesa_id):
    """
    Devuelve (solo staff) los slots disponibles de una mesa en un día.
    GET: ?fecha=YYYY-MM-DD  (default hoy local)
         ?party=2 (opcional)
    """
    from .utils import booking_total_minutes  # <-- helper de duración dinámica

    mesa = get_object_or_404(Mesa, pk=mesa_id)

    # fecha
    fecha_q = request.GET.get("fecha", "")
    try:
        if fecha_q:
            y, m, d = [int(x) for x in fecha_q.split("-")]
            d_dia = date(y, m, d)
        else:
            d_dia = timezone.localdate()
    except Exception:
        d_dia = timezone.localdate()

    # party
    try:
        party = int((request.GET.get("party") or "2").strip())
    except Exception:
        party = 2

    # slots disponibles considerando duración dinámica por party y hora
    slots_dt = _slots_disponibles(mesa, d_dia, party=party)

    # duración “base” que mostraremos junto con la respuesta
    tz = timezone.get_current_timezone()
    totalmin = booking_total_minutes(
        timezone.make_aware(datetime(d_dia.year, d_dia.month, d_dia.day, 0, 0), tz),
        party
    )

    # formateo HH:MM local
    slots_str = [s.astimezone(tz).strftime("%H:%M") for s in slots_dt]

    return JsonResponse({
        "mesa": mesa.id,
        "fecha": d_dia.isoformat(),
        "duracion_min": totalmin,
        "slots": slots_str,
    })


@require_POST
@staff_member_required
@transaction.atomic
def admin_finalizar_reserva(request, reserva_id):
    """
    Finaliza una reserva (libera mesa). Solo si ya se confirmó la llegada.
    Acepta POST opcional dt="YYYY-MM-DD HH:MM" para fijar la hora de liberación.
    """
    r = get_object_or_404(Reserva.objects.select_for_update(), pk=reserva_id)

    if not _puede_ver_sucursal(request.user, r.mesa.sucursal):
        return HttpResponseForbidden("No tienes permiso para operar esta reserva.")

    # Regla: solo si ya hubo check-in
    if not getattr(r, "llego", False):
        messages.error(request, "Primero confirma la llegada para poder finalizar la reserva.")
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)

    # Hora opcional
    tz = timezone.get_current_timezone()
    dt_txt = (request.POST.get("dt") or "").strip()
    dt = None
    if dt_txt:
        try:
            dt = timezone.make_aware(datetime.strptime(dt_txt, "%Y-%m-%d %H:%M"), tz)
        except Exception:
            dt = None

    r.marcar_liberada(dt or timezone.now())

    hora_local = timezone.localtime(r.liberada_en).strftime("%H:%M")
    messages.success(request, f"Reservación finalizada. Mesa liberada desde las {hora_local}.")

    # Redirección
    next_param = (request.POST.get("next") or request.GET.get("next") or "").lower()
    if next_param == "mesa":
        return redirect("reservas:admin_mesa_detalle", mesa_id=r.mesa_id)
    return redirect("reservas:admin_mapa_sucursal", sucursal_id=r.mesa.sucursal_id)


@require_http_methods(["POST", "GET"])
def reservar_auto(request, sucursal_id):
    """
    Crea una reserva automática asignando mesa según disponibilidad.
    Compatible con modelo IHOP (campos: fecha, inicio_utc, fin_utc, num_personas, estado, etc.)
    Maneja correctamente zonas horarias de sucursal.
    """
    from datetime import timezone as py_tz

    # 1) Obtener sucursal con seguridad
    s = _get_sucursal_scoped(request, sucursal_id)

    # 2) Zona horaria local
    tz = _tz_for_sucursal(s)

    # 3) Parámetros recibidos
    date_str = (request.POST.get("date") or request.GET.get("date") or "").strip()
    time_str = (request.POST.get("time") or request.GET.get("time") or "").strip()
    party_raw = (request.POST.get("party") or request.GET.get("party") or "2").strip()

    try:
        party = max(1, int(party_raw))
    except Exception:
        party = 2

    # 4) Si no hay fecha/hora, usar actual +15 min
    now_loc = timezone.localtime(timezone.now(), tz)
    if date_str and time_str:
        try:
            dt_local = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            dt_local = timezone.make_aware(dt_local, tz)
        except Exception:
            dt_local = (now_loc + timedelta(minutes=15)).replace(second=0, microsecond=0)
    else:
        dt_local = (now_loc + timedelta(minutes=15)).replace(second=0, microsecond=0)

    # 5) Autoasignación de mesa
    try:
        mesa = asignar_mesa_automatica(s, dt_local, party)
    except Exception as e:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": "no_table", "detail": str(e)}, status=200)
        from django.contrib import messages
        messages.error(request, "No hay mesas disponibles para ese horario.")
        return redirect("reservas:sucursal_detalle", slug=s.slug)

    # 6) Calcular fin de reserva
    dur_min = booking_total_minutes(dt_local, party)
    dt_fin_local = dt_local + timedelta(minutes=dur_min)

    # 7) Convertir a UTC
    inicio_utc = dt_local.astimezone(py_tz.utc)
    fin_utc = dt_fin_local.astimezone(py_tz.utc)

    # 8) Cliente (si está logueado)
    cliente = getattr(request.user, "cliente", None)

    # 9) Crear la reserva
    reserva = Reserva.objects.create(
        sucursal=s,
        mesa=mesa,
        cliente=cliente,
        fecha=dt_local.date(),
        inicio_utc=inicio_utc,
        fin_utc=fin_utc,
        local_service_date=dt_local.date(),
        local_inicio=dt_local,
        local_fin=dt_fin_local,
        num_personas=party,
        estado="CONF",  # ✅ según tus choices reales
    )

    # 10) Mensaje de éxito
    from django.contrib import messages
    messages.success(request, "¡Reserva creada correctamente!")
    return redirect("reservas:reserva_detalle", pk=reserva.pk)




def _staff_puede_gestionar_reserva(user, reserva):
    # Ajusta a tu modelo de permisos. Ejemplo con PerfilAdmin.sucursal_asignada:
    if user.is_superuser:
        return True
    if not user.is_staff:
        return False
    perfil = getattr(user, "perfiladmin", None)
    if perfil and getattr(perfil, "sucursal_asignada_id", None) == reserva.mesa.sucursal_id:
        return True
    return False

@login_required
def admin_reasignar_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    if not _staff_puede_gestionar_reserva(request.user, reserva):
        messages.error(request, "No tienes permisos para gestionar esta reserva.")
        return redirect("/")

    if request.method == "POST":
        mesa_id = request.POST.get("mesa_id")
        forzar = bool(request.POST.get("forzar"))
        nueva_mesa = get_object_or_404(Mesa, pk=mesa_id, sucursal=reserva.mesa.sucursal)

        ok, motivo = mover_reserva(reserva, nueva_mesa, forzar=forzar)
        if ok:
            messages.success(request, motivo)
        else:
            messages.error(request, motivo)

        # AJUSTA este reverse al nombre de tu panel de mesas
        try:
            return redirect(reverse("reservas:panel_mesas", args=[reserva.mesa.sucursal_id]))
        except Exception:
            return redirect("/")

    # GET: mostrar candidatas
    forzar = bool(request.GET.get("forzar"))
    candidatas = mesas_disponibles_para_reserva(reserva, forzar=forzar)
    contexto = {
        "reserva": reserva,
        "candidatas": candidatas,
        "forzar": forzar,
    }
    return render(request, "reservas/admin_reasignar_reserva.html", contexto)



@login_required
def reservar_slot(request, sucursal_id):
    s = get_object_or_404(Sucursal, pk=sucursal_id, activo=True)

    # Activar TZ de la sucursal para esta request
    try:
        dj_tz.activate(ZoneInfo(s.timezone))
    except Exception:
        dj_tz.deactivate()

    fecha_str = (request.GET.get("fecha") or "").strip()  # YYYY-MM-DD
    hora_sugerida = (request.GET.get("hora") or "").strip()  # HH:MM

    if not fecha_str:
        messages.error(request, "Selecciona una fecha válida.")
        return redirect("reservas:sucursal_detalle", slug=s.slug)

    # Sugerir hora local redondeada si no viene
    if not hora_sugerida:
        now_local = dj_tz.localtime()
        mins = ((now_local.minute // 15) + 1) * 15
        if mins >= 60:
            now_local = now_local.replace(hour=(now_local.hour + 1) % 24, minute=0, second=0, microsecond=0)
        else:
            now_local = now_local.replace(minute=mins, second=0, microsecond=0)
        hora_sugerida = now_local.strftime("%H:%M")

    # Prefijo telefónico por país (ajusta a tu modelo; si ya tienes campo, úsalo)
    iso2 = getattr(getattr(s, "pais", None), "iso2", "MX")
    prefix_map = {"MX": "+52", "AR": "+54", "ES": "+34", "US": "+1"}
    phone_prefix = prefix_map.get(iso2, "+52")

    contexto = {
        "sucursal": s,
        "fecha": fecha_str,
        "hora_sugerida": hora_sugerida,  # HH:MM local
        "party_default": 2,
        "cap_max": 12,
        "phone_prefix": phone_prefix,     # 👈 para el template
    }
    return render(request, "reservas/reservar_slot.html", contexto)






@staff_member_required
def admin_mesas_disponibles(request, sucursal_id):
    _ensure_staff_or_404(request)

    from .utils import _auto_cancel_por_tolerancia, booking_total_minutes
    _auto_cancel_por_tolerancia(minutos=6)

    sucursal = get_object_or_404(Sucursal, id=sucursal_id)

    # 🔒 NUEVO: proteger por sucursal
    if not _puede_ver_sucursal(request.user, sucursal):
        raise Http404()  # o HttpResponseForbidden("No tienes permiso")

    inicio, fin = _slot_consultado(request)
    estados_ocupan = ["PEND", "CONF"]

    try:
        party = int((request.GET.get("party") or "2").strip())
    except Exception:
        party = 2

    total_min = booking_total_minutes(inicio, party)
    mesas_qs = Mesa.objects.filter(sucursal=sucursal)

    reservas_existe = (
        Reserva.objects
        .filter(mesa=OuterRef("pk"), estado__in=estados_ocupan, fecha__lt=fin)
        .annotate(fin_res=Case(default=Value(0), output_field=BooleanField()))
        .filter(fecha__gt=inicio - timedelta(minutes=total_min))
    )

    mesas = (
        mesas_qs
        .annotate(ocupada=Exists(reservas_existe))
        .annotate(disponible=Case(When(ocupada=True, then=Value(False)), default=Value(True), output_field=BooleanField()))
        .order_by("numero", "id")
    )

    ctx = {"sucursal": sucursal, "mesas": mesas, "slot_inicio": inicio, "slot_fin": fin}
    return render(request, "reservas/ver_mesas.html", ctx)





# views.py (filtro por sucursal del staff)


def sucursales_permitidas_ids(user):
    # Adapta a tu modelo (PerfilAdmin / relaciones)
    if user.is_superuser:
        return Sucursal.objects.values_list("id", flat=True)
    return user.perfiladmin.sucursales.values_list("id", flat=True)

@staff_member_required
def panel_mesas(request):
    ids = sucursales_permitidas_ids(request.user)
    mesas = Mesa.objects.filter(sucursal_id__in=ids)
    # ...
    return render(request, "admin/panel_mesas.html", {"mesas": mesas})



# views.py


@ratelimit(key="ip", rate="5/m", block=True)
def account_login(request):
    # login view
    ...

@staff_member_required
@ratelimit(key="ip", rate="60/m", block=True)
def api_slots(request, sucursal_id):
    # devuelve slots; valida también sucursal_id dentro de ids permitidos
    ...



# reservas/views.py
def api_public_slots(request, sucursal_id):
    fecha = request.GET.get("fecha")   # YYYY-MM-DD
    party = int(request.GET.get("party", 2))

    slots = get_slots_sucursal(sucursal_id, fecha, party, limit=10)
    return JsonResponse({"slots": slots})




def healthz(request):
    return JsonResponse({"ok": True})

def readyz(request):
    status = {"db": False, "cache": False}
    # DB
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1;")
        status["db"] = True
    except Exception:
        status["db"] = False
    # Cache
    try:
        cache.set("readyz_ping", "1", 5)
        status["cache"] = cache.get("readyz_ping") == "1"
    except Exception:
        status["cache"] = False

    ok = all(status.values())
    return JsonResponse({"ok": ok, **status}, status=200 if ok else 500)







@staff_member_required
@require_GET
def staff_api_disponibilidad(request):
    """
    Shim: redirige a la API pública /api/sucursal/<id>/slots/ manteniendo querystring.
    Evita 400 del endpoint staff mientras implementas la lógica propia.
    """
    suc_id = request.GET.get("sucursal_id")
    # Si no viene en el query, intenta tomar la del PerfilAdmin:
    if not suc_id and hasattr(request.user, "perfiladmin") and request.user.perfiladmin.sucursal_asignada_id:
        suc_id = str(request.user.perfiladmin.sucursal_asignada_id)
    if not suc_id:
        return HttpResponseRedirect(reverse("reservas:api_slots_sucursal", args=[0]))  # caerá en 404 controlado

    base = reverse("reservas:api_slots_sucursal", args=[int(suc_id)])
    qs = request.META.get("QUERY_STRING", "")
    url = f"{base}?{qs}" if qs else base
    return HttpResponseRedirect(url)



def _puede_ver_sucursal(user, sucursal):
    if not user.is_authenticated or not user.is_staff:
        return False
    if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
        return True
    # Admin asignado por perfil
    perfil = getattr(user, "perfiladmin", None)
    if perfil and perfil.sucursal_asignada_id == sucursal.id:
        return True
    # Admin por M2M
    return sucursal.administradores.filter(pk=user.pk).exists()



@login_required
@require_POST
def admin_api_mesa_setpos(request, mesa_id):
    """
    Guarda la posición (pos_x, pos_y) de una mesa en px relativos al canvas.
    Espera POST con x, y (ints).
    """
    mesa = get_object_or_404(Mesa, pk=mesa_id)
    if not _puede_ver_sucursal(request.user, mesa.sucursal):
        return HttpResponseForbidden("Sin permiso")

    try:
        x = int(request.POST.get("x", "0"))
        y = int(request.POST.get("y", "0"))
    except ValueError:
        return JsonResponse({"ok": False, "error": "coords_invalidas"}, status=400)

    # Opcional: límites mínimos
    if x < 0: x = 0
    if y < 0: y = 0

    mesa.pos_x = x
    mesa.pos_y = y
    mesa.save(update_fields=["pos_x", "pos_y"])
    return JsonResponse({"ok": True, "x": x, "y": y})





@login_required
@require_POST
def admin_api_mesa_pos(request, mesa_id):
    mesa = get_object_or_404(Mesa, pk=mesa_id)
    # misma regla de visibilidad que usas en el resto:
    if not _puede_ver_sucursal(request.user, mesa.sucursal):
        return HttpResponseForbidden("Sin permiso.")

    try:
        data = json.loads(request.body.decode("utf-8"))
        pos_x = float(data.get("pos_x"))
        pos_y = float(data.get("pos_y"))
    except Exception:
        return HttpResponseBadRequest("payload inválido")

    # acotar a 0..100
    pos_x = max(0.0, min(100.0, pos_x))
    pos_y = max(0.0, min(100.0, pos_y))

    mesa.pos_x = pos_x
    mesa.pos_y = pos_y
    mesa.save(update_fields=["pos_x", "pos_y"])

    return JsonResponse({"ok": True, "pos_x": float(mesa.pos_x), "pos_y": float(mesa.pos_y)})



@login_required
@require_POST
def admin_api_recepcion_pos(request, sucursal_id):
    # permisos básicos: que el usuario pueda ver/gestionar esta sucursal
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)

    # (opcional) si tienes helper de visibilidad, úsalo aquí
    # if not Sucursal.objects.visibles_para(request.user).filter(pk=sucursal_id).exists():
    #     return HttpResponseForbidden("No autorizado")

    try:
        data = json.loads(request.body.decode("utf-8"))
        x = float(data.get("pos_x", 0))
        y = float(data.get("pos_y", 0))
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    # clamp 0..100 y redondeo a 2 decimales
    x = max(0.0, min(100.0, round(x, 2)))
    y = max(0.0, min(100.0, round(y, 2)))

    sucursal.recepcion_x = int(round(x))
    sucursal.recepcion_y = int(round(y))
    sucursal.save(update_fields=["recepcion_x", "recepcion_y"])

    return JsonResponse({"ok": True, "x": sucursal.recepcion_x, "y": sucursal.recepcion_y})





# --- Nueva vista para editar una mesa desde el mapa ---
from django import forms

@staff_member_required
def admin_mesa_editar(request, mesa_id):
    """
    Formulario para editar una mesa desde el mapa interactivo.
    Si se guarda correctamente, redirige de nuevo al mapa de la sucursal.
    """
    mesa = get_object_or_404(Mesa, pk=mesa_id)
    sucursal = mesa.sucursal

    # Verifica permiso de visibilidad
    if not _puede_ver_sucursal(request.user, sucursal):
        return HttpResponseForbidden("No tienes permiso para editar mesas de esta sucursal.")

    class MesaEditForm(forms.ModelForm):
        class Meta:
            model = Mesa
            fields = ["numero", "capacidad", "zona", "ubicacion", "notas", "bloqueada"]
            widgets = {
                "zona": forms.Select(choices=[
                    ("interior", "Interior"),
                    ("terraza", "Terraza"),
                    ("exterior", "Exterior"),
                ]),
                "notas": forms.Textarea(attrs={"rows": 2}),
            }

    if request.method == "POST":
        form = MesaEditForm(request.POST, instance=mesa)
        if form.is_valid():
            form.save()
            messages.success(request, "✅ Mesa actualizada correctamente.")
            return redirect("reservas:admin_mapa_sucursal", sucursal_id=sucursal.id)
        else:
            messages.error(request, "Revisa los campos del formulario.")
    else:
        form = MesaEditForm(instance=mesa)

    ctx = {
        "mesa": mesa,
        "sucursal": sucursal,
        "form": form,
    }
    return render(request, "reservas/admin_mesa_editar.html", ctx)




@staff_member_required
def admin_bloqueos(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
    if not _puede_ver_sucursal(request.user, sucursal):
        return HttpResponseForbidden("Sin permiso sobre la sucursal.")
    # Traemos mesas para filtros
    mesas = Mesa.objects.filter(sucursal=sucursal).order_by("numero", "id")
    return render(request, "reservas/admin_bloqueos.html", {
        "sucursal": sucursal,
        "mesas": mesas,
    })



# reservas/views.py

def sucursales_grid(request):
    q = request.GET.get("q", "").strip()
    hoy = timezone.localdate()

    base = Sucursal.objects.filter(activo=True).annotate(
        reservas_hoy=Count("reservas", filter=Q(reservas__fecha=hoy))
    )

    # Limitar por país si es Country Admin
    qs = scope_sucursales_for(request, base).order_by("nombre")

    # Si es Branch Admin (staff sin países asignados), limitar a sus sucursales
    if (request.user.is_authenticated and request.user.is_staff
        and not request.user.is_superuser
        and not user_allowed_countries(request.user).exists()):
        qs = qs.filter(administradores=request.user)

    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) |
            Q(direccion__icontains=q) |
            Q(codigo_postal__icontains=q) |
            Q(cocina__icontains=q)
        )

    return render(request, "reservas/sucursales_grid.html", {
        "sucursales": qs,
        "q": q,
    })




def store_locator(request):
    qs = scope_sucursales_for(request, Sucursal.objects.filter(activo=True))
    return render(request, "reservas/store_locator.html", {"sucursales": qs})







def sucursales_grid(request):
    user_country = get_effective_country(request)
    q = request.GET.get("q", "")
    hoy = timezone.localdate()

    sucursales = (
        Sucursal.objects
        .filter(pais=user_country)
        .annotate(reservas_hoy=Count("reservas", filter=Q(reservas__fecha=hoy)))
        .order_by("nombre")
    )
    if q:
        sucursales = sucursales.filter(Q(nombre__icontains=q) | Q(ciudad__icontains=q))

    return render(request, "reservas/sucursales_grid.html", {
        "sucursales": sucursales,
        "q": q,
        "user_country": user_country,
    })



# ===============================
#   REGISTER
# ===============================

def register(request):
    if request.method == 'POST':
        form = ClienteRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('reservas:home')
    else:
        form = ClienteRegistrationForm()
    return render(request, 'reservas/register.html', {'form': form})


def _get_sucursal_scoped(request, sucursal_id: int) -> Sucursal:
    """
    Obtiene la sucursal respetando el alcance:
    - Clientes: sólo sucursales del país efectivo.
    - Staff: respeta scope_sucursales_for.
    """
    base = Sucursal.objects.filter(activo=True)

    if request.user.is_authenticated and request.user.is_staff:
        qs = scope_sucursales_for(request, base)
    else:
        user_country = get_effective_country(request)
        qs = base.filter(pais=user_country)

    return get_object_or_404(qs, pk=sucursal_id)


# tu helper existente
# _tz_for_sucursal(sucursal)  -> devuelve ZoneInfo de la sucursal

@login_required
def reserva_detalle(request, pk):
    """
    Ticket/recibo de la reserva con QR (sin código de barras).
    """
    reserva = get_object_or_404(
        Reserva.objects.select_related("sucursal", "mesa", "cliente", "cliente__user"),
        pk=pk,
    )

    # TZ de sucursal
    tz = _tz_for_sucursal(reserva.sucursal or (getattr(reserva, "mesa", None) and reserva.mesa.sucursal))

    # Normaliza locales
    li = reserva.local_inicio or (reserva.inicio_utc and timezone.localtime(reserva.inicio_utc, tz))
    lf = reserva.local_fin    or (reserva.fin_utc   and timezone.localtime(reserva.fin_utc, tz))

    fecha_txt = formats.date_format(li.date(), "DATE_FORMAT") if li else ""
    hora_txt  = li.strftime("%H:%M") if li else ""
    duracion_min = int(((lf - li).total_seconds() // 60)) if (li and lf) else 0

    # Contacto fallbacks
    cliente = getattr(reserva, "cliente", None)
    user = getattr(cliente, "user", None)

    contacto_nombre = (
        (reserva.nombre_contacto or "").strip()
        or (getattr(cliente, "nombre", "") or "").strip()
        or (" ".join(filter(None, [getattr(user, "first_name", ""), getattr(user, "last_name", "")])).strip() if user else "")
        or (getattr(user, "username", "") if user else "")
    )

    contacto_email = (
        (reserva.email_contacto or "").strip()
        or (getattr(cliente, "email", "") or "").strip()
        or (getattr(user, "email", "") if user else "")
    )

    contacto_tel = (
        (reserva.telefono_contacto or "").strip()
        or (getattr(cliente, "telefono", "") or "").strip()
    )

    # URL absoluta para el QR (entrada por folio)
    qr_url = request.build_absolute_uri(
        reverse("reservas:reserva_scan_entry", args=[reserva.folio])
    )

    ctx = {
        "reserva": reserva,
        "fecha_txt": fecha_txt,
        "hora_txt": hora_txt,
        "duracion_min": duracion_min,
        "personas": reserva.num_personas,
        "contacto_nombre": contacto_nombre,
        "contacto_email": contacto_email,
        "contacto_tel": contacto_tel,
        "notas": getattr(reserva, "notas", "") or "",
        "qr_url": qr_url,
    }
    return render(request, "reservas/reserva_exito.html", ctx)



# --- Helper contacto/fallbacks ----------------------------------------------
def _contacto_from_reserva(reserva):
    """
    Devuelve un dict con nombre/email/tel usando fallbacks:
    Reserva -> Cliente -> User.
    """
    cliente = getattr(reserva, "cliente", None)
    user = getattr(cliente, "user", None)

    nombre = (
        (reserva.nombre_contacto or "").strip()
        or (getattr(cliente, "nombre", "") or "").strip()
        or (
            (" ".join([
                (getattr(user, "first_name", "") or "").strip(),
                (getattr(user, "last_name", "") or "").strip()
            ])).strip() if user else ""
        )
        or (getattr(user, "username", "") if user else "")
        or ""
    )
    email = (
        (reserva.email_contacto or "").strip()
        or (getattr(cliente, "email", "") or "").strip()
        or (getattr(user, "email", "") if user else "")
        or ""
    )
    tel = (
        (reserva.telefono_contacto or "").strip()
        or (getattr(cliente, "telefono", "") or "").strip()
        or ""
    )
    return {"contacto_nombre": nombre, "contacto_email": email, "contacto_tel": tel}




# ⬇️ AJUSTA estos imports a tus modelos reales si difieren

@staff_member_required
@require_GET
def orden_mesa_nueva(request):
    """
    Crea (o reutiliza) una Orden en estado DRAFT para la mesa indicada
    y devuelve el HTML del modal renderizado dentro de JSON.
    """
    mesa_id = request.GET.get("mesa_id")
    if not mesa_id:
        return JsonResponse({"ok": False, "error": "mesa_id requerido"}, status=400)

    mesa = get_object_or_404(Mesa, pk=mesa_id)

    # Reutiliza una orden DRAFT abierta para esa mesa, o crea una nueva
    orden, _created = Orden.objects.get_or_create(
        mesa=mesa,
        estado="DRAFT",                 # ajusta si tu campo/choice se llama distinto
        defaults={
            "sucursal": getattr(mesa, "sucursal", None),
        },
    )

    html = render_to_string(
        "reservas/orden_modal_body.html",
        {
            "sucursal": getattr(mesa, "sucursal", None),
            "mesa": mesa,
            "orden": orden,
        },
        request=request,
    )
    return JsonResponse({"ok": True, "html": html})


@staff_member_required
@require_GET
def api_menu_buscar(request):
    """
    Búsqueda rápida de productos del menú.
    Respuesta: {"results":[{"id":..,"codigo":"..","nombre":"..","precio":..}, ...]}
    """
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    qs = MenuItem.objects.all()
    # filtros sencillos por código o nombre
    qs = qs.filter(nombre__icontains=q)[:25]

    results = [
        {
            "id": mi.id,
            "codigo": getattr(mi, "codigo", "") or "",
            "nombre": mi.nombre,
            "precio": float(getattr(mi, "precio", 0) or 0),
        }
        for mi in qs
    ]
    return JsonResponse({"results": results})


@staff_member_required
@require_POST
@transaction.atomic
def api_orden_crear(request):
    """
    Agrega un item a la Orden.
    Body JSON admite:
      - orden_id (req)
      - item_id (opcional)  ó  codigo (opcional)  ó  nombre (opcional)
      - cantidad (default 1)
      - notas (opcional)
    Respuesta: {ok, html} con el cuerpo del modal re-renderizado.
    """
    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return HttpResponseBadRequest("JSON inválido")

    orden_id = data.get("orden_id")
    if not orden_id:
        return JsonResponse({"ok": False, "error": "orden_id requerido"}, status=400)

    orden = get_object_or_404(Orden, pk=orden_id)

    cantidad = int(data.get("cantidad") or 1)
    if cantidad < 1:
        cantidad = 1

    menu_item = None
    item_id = data.get("item_id")
    codigo = (data.get("codigo") or "").strip()
    nombre = (data.get("nombre") or "").strip()

    if item_id:
        menu_item = get_object_or_404(MenuItem, pk=item_id)
    elif codigo:
        menu_item = MenuItem.objects.filter(codigo__iexact=codigo).first()
    elif nombre:
        # Estrategia básica: nombre exacto; ajusta a icontains si lo prefieres
        menu_item = MenuItem.objects.filter(nombre__iexact=nombre).first()

    if not menu_item:
        return JsonResponse({"ok": False, "error": "Producto no encontrado"}, status=404)

    # Crear renglón de Orden
    OrdenItem.objects.create(
        orden=orden,
        codigo=getattr(menu_item, "codigo", "") or "",
        nombre=menu_item.nombre,
        precio_unit=getattr(menu_item, "precio", 0) or 0,
        cantidad=cantidad,
        notas=(data.get("notas") or "").strip(),
    )

    # Re-render del parcial
    html = render_to_string(
        "reservas/orden_modal_body.html",
        {
            "sucursal": getattr(orden, "sucursal", getattr(orden.mesa, "sucursal", None)),
            "mesa": orden.mesa,
            "orden": orden,
        },
        request=request,
    )
    return JsonResponse({"ok": True, "html": html})
