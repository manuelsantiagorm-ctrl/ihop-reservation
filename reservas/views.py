# reservas/views.py
import os
import json
import logging
from datetime import datetime, date, time, timedelta
from math import radians, cos, sin, asin, sqrt
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseRedirect
from django.db import connection, transaction
from django.db.models import Q, Exists, OuterRef, Value, BooleanField, Case, When
from django.core.cache import cache
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from .helpers.permisos import assert_can_manage
from django.utils import timezone, formats
from django.db.models import Count
from django.utils.dateparse import parse_datetime
from django.utils.safestring import mark_safe
from django.utils.dateparse import parse_date
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.http import  HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt 
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden, HttpResponseRedirect, Http404

from .utils import mesas_disponibles_para_reserva, mover_reserva, booking_total_minutes, asignar_mesa_automatica
from .emails import enviar_correo_reserva_confirmada
from .forms import (
    WalkInReservaForm, ClientePerfilForm, ClienteRegistrationForm, ReservaForm,
    SucursalForm, SucursalFotoForm, SucursalFotoFormSet,
)
from .models import (
    Cliente, Mesa, Reserva, Sucursal, SucursalFoto, PerfilAdmin, BloqueoMesa,
)

# --- Rate limit (shim para que migrate no truene si falta la lib) ---
try:
    from ratelimit.decorators import ratelimit
except Exception:
    def ratelimit(*args, **kwargs):
        def _inner(view):
            return view
        return _inner




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
from django.utils import timezone
# Opcional si quieres anotar reservas_hoy:
# from django.db.models import Count, Q

@login_required
def home(request):
    user = request.user
    is_admin_staff = user.is_staff

    if user.is_superuser:
        admin_sucursales = Sucursal.objects.all().order_by("nombre")
    elif is_admin_staff:
        admin_sucursales = Sucursal.objects.filter(administradores=user).order_by("nombre")
    else:
        admin_sucursales = Sucursal.objects.none()

    cliente = getattr(user, "cliente", None)
    todas = Sucursal.objects.filter(activo=True).order_by("nombre")

    # ===== Carrusel: 12 sucursales =====
    sucursales = list(todas[:12])

    # >>> Añadimos 3 horarios mock por sucursal (13:00, 13:15, 13:30)
    def fmt(t: time) -> str:
        # 01:00 pm -> 1:00 p. m. (estilo OpenTable; ajusta si quieres)
        return t.strftime("%I:%M %p").lower().replace("am", "a. m.").replace("pm", "p. m.").lstrip("0")

    sugerencias_mock = [fmt(time(13, 0)), fmt(time(13, 15)), fmt(time(13, 30))]
    for s in sucursales:
        s.sugerencias = sugerencias_mock

    # ===== Recomendadas / Otras (tu lógica) =====
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
        "sucursales": sucursales,                # <-- alimenta el carrusel
        "sucursales_recomendadas": recomendadas_qs,
        "otras_sucursales": otras_qs,
        "hoy": timezone.localdate(),
        "party_range": range(1, 13),
        "party_default": "2",
    }
    return render(request, "reservas/home.html", ctx)


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
         lat, lng, radius_km | km (radio en km)
    """
    q = request.GET.get("q", "").strip()
    date_str = request.GET.get("date")
    time_str = request.GET.get("time")
    party = request.GET.get("party")
    lat = request.GET.get("lat")
    lng = request.GET.get("lng")

    # radius_km o km (alias)
    radius_str = request.GET.get("radius_km", request.GET.get("km", "50"))
    try:
        radius_km = float(radius_str)
    except Exception:
        radius_km = 50.0

    now = timezone.localtime()
    base_dt = now
    try:
        if date_str:
            if time_str:
                base_dt = timezone.make_aware(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
            else:
                base_dt = timezone.make_aware(datetime.strptime(f"{date_str} 19:00", "%Y-%m-%d %H:%M"))
    except Exception:
        base_dt = now

    qs = Sucursal.objects.filter(activo=True)
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) |
            Q(direccion__icontains=q) |
            Q(codigo_postal__icontains=q) |
            Q(cocina__icontains=q)
        )

    user_lat = user_lng = None
    results_raw = []

    # --- MODO CERCA DE MÍ ---
    if lat and lng:
        try:
            user_lat, user_lng = float(lat), float(lng)
        except ValueError:
            user_lat = user_lng = None

    if user_lat is not None and user_lng is not None:
        # Calcular distancias y (opcional) filtrar por radio
        for s in qs:
            s_lat, s_lng = _coords_from_sucursal(s)
            d = None
            if s_lat is not None and s_lng is not None:
                d = _haversine_km(user_lat, user_lng, s_lat, s_lng)
                if d > radius_km:
                    continue  # fuera del radio solicitado

            results_raw.append({
                "obj": s,
                "map_lat": s_lat,         # para link de Mapa en el template
                "map_lng": s_lng,
                "distance_km": (None if d is None else round(d, 1)),
                "proximos_slots": _proximos_slots(base_dt, 3),
            })

        # Orden: primero con distancia (menor a mayor), luego sin distancia
        results_raw.sort(key=lambda item: (item["distance_km"] is None, item["distance_km"] or 0.0))

    else:
        # --- MODO NORMAL (tu orden original) ---
        qs = qs.order_by("-recomendado", "nombre")
        for s in qs:
            s_lat, s_lng = _coords_from_sucursal(s)
            results_raw.append({
                "obj": s,
                "map_lat": s_lat,
                "map_lng": s_lng,
                "distance_km": None,
                "proximos_slots": _proximos_slots(base_dt, 3),
            })

    # Paginación sobre la lista ya ordenada
    paginator = Paginator(results_raw, 12)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    ctx = {
        "q": q,
        "date": date_str or timezone.localdate().strftime("%Y-%m-%d"),
        "time": time_str or "19:00",
        "party": party or "2",
        "page_obj": page_obj,
        "results": list(page_obj.object_list),  # cada item: {"obj","map_lat","map_lng","distance_km","proximos_slots"}
        "party_range": range(1, 13),
        "user_lat": user_lat,
        "user_lng": user_lng,
        "radius_km": int(radius_km),
    }
    return render(request, "reservas/seleccionar_sucursal.html", ctx)


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
    reserva = get_object_or_404(
        Reserva.objects.select_related("mesa", "mesa__sucursal", "cliente"),
        id=reserva_id,
        cliente__user=request.user,
    )
    return render(
        request,
        "reservas/reserva_exito.html",
        {
            "reserva": reserva,
            "tolerancia_min": int(getattr(settings, "CHECKIN_TOLERANCIA_MIN", 5)),
        },
    )



@login_required
def mis_reservas(request):
    from .utils import _auto_cancel_por_tolerancia
    _auto_cancel_por_tolerancia(minutos=6)

    cliente = request.user.cliente
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
from django.contrib.admin.views.decorators import staff_member_required

@staff_member_required
def ver_mesas(request, sucursal_id):
    from .utils import _auto_cancel_por_tolerancia
    from .utils import booking_total_minutes
    _auto_cancel_por_tolerancia(minutos=6)

    sucursal = get_object_or_404(Sucursal, id=sucursal_id)

    # 🔒 NUEVO: proteger por sucursal
    if not _puede_ver_sucursal(request.user, sucursal):
        raise Http404()  # o: return HttpResponseForbidden("No tienes permiso para esta sucursal.")

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

    tz = timezone.get_current_timezone()
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



from django.views.decorators.http import require_POST

@staff_member_required
def admin_mesa_crear(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id)
    if request.method == "POST":
        numero = int(request.POST.get("numero"))
        capacidad = int(request.POST.get("capacidad") or 4)
        zona = request.POST.get("zona") or "interior"

        Mesa.objects.create(
            sucursal=sucursal,
            numero=numero,
            capacidad=capacidad,
            zona=zona,
            ubicacion=request.POST.get("ubicacion") or "",
            notas=request.POST.get("notas") or "",
        )

        return redirect("reservas:admin_mapa_sucursal", sucursal.id)

# reservas/views.py



def _proximos_slots(base_dt, n=3, paso_min=15):
    """
    Devuelve N horarios próximos como strings (ej: '7:30 pm').
    Compatible con Windows y Linux/Mac.
    """
    start = base_dt.replace(second=0, microsecond=0)
    resto = start.minute % paso_min
    if resto:
        start += timedelta(minutes=paso_min - resto)

    slots = []
    cur = start
    for _ in range(n):
        dt_local = timezone.localtime(cur)
        if os.name == "nt":
            # Windows: %#I quita el cero a la izquierda
            s = dt_local.strftime("%#I:%M %p")
        else:
            # Unix: %-I quita el cero a la izquierda
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

    # 1) Superuser o Dueño de Cadena => ve todas
    if u.is_superuser or (u.is_staff and u.has_perm("reservas.manage_branches")):
        sucursales = Sucursal.objects.all().order_by("id")
        return render(request, "reservas/admin_sucursales.html", {"sucursales": sucursales})

    # 2) Admin de sucursal => solo su sucursal asignada
    perfil = PerfilAdmin.objects.filter(user=u).select_related("sucursal_asignada").first()
    if perfil and perfil.sucursal_asignada_id:
        sucursales = Sucursal.objects.filter(pk=perfil.sucursal_asignada_id)
        return render(request, "reservas/admin_sucursales.html", {"sucursales": sucursales})

    # 3) Si no tiene sucursal asignada
    messages.info(request, "No tienes sucursal asignada.")
    return render(request, "reservas/admin_sucursales.html", {"sucursales": []})



def sucursal_detalle(request, slug):
    s = get_object_or_404(Sucursal.objects.filter(activo=True), slug=slug)

    date_str = request.GET.get("date")
    time_str = request.GET.get("time")
    party = (request.GET.get("party") or "2").strip()

    now = timezone.localtime()
    try:
        if date_str:
            base_dt = timezone.make_aware(
                datetime.strptime(f"{date_str} {time_str or '19:00'}", "%Y-%m-%d %H:%M")
            )
        else:
            base_dt = now
    except Exception:
        base_dt = now

    try:
        precio_signos = "$" * int(s.precio_nivel or 1)
    except Exception:
        precio_signos = "$"

    proximos = _proximos_slots(base_dt, 5)

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
        "date": date_str or timezone.localdate().strftime("%Y-%m-%d"),
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
    # --- imports de utilidades (con fallback para parseo de fecha) ---
    from .utils import booking_total_minutes, _slots_disponibles
    try:
        # si tienes un parser propio lo usamos
        from .utils import _parse_fecha_param as _parse_fecha_param_util
    except Exception:
        _parse_fecha_param_util = None

    # ---------- parámetros ----------
    # fecha (YYYY-MM-DD); tolera 'date' como alias y cae a hoy si viene mal
    fecha_raw = (request.GET.get("fecha") or request.GET.get("date") or "").strip()
    if _parse_fecha_param_util:
        dia = _parse_fecha_param_util(fecha_raw)
    else:
        dia = parse_date(fecha_raw) if fecha_raw else None
    if dia is None:
        dia = timezone.localdate()  # no rompemos; devolvemos slots para hoy si procede

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

    # sucursal (activa)
    sucursal = get_object_or_404(Sucursal, pk=sucursal_id, activo=True)

    tz = timezone.get_current_timezone()
    now_loc = timezone.localtime()

    # ---------- ancla de tiempo ----------
    # si es hoy, no permitimos ir al pasado; si es otro día, usamos hora de apertura
    hraw = (request.GET.get("hora") or request.GET.get("time") or "").strip().lower()
    anchor = None
    for fmt in ("%H:%M", "%I:%M%p", "%I:%M %p", "%H", "%I%p", "%I %p"):
        try:
            t = datetime.strptime(hraw, fmt).time()
            anchor = timezone.make_aware(datetime.combine(dia, t), tz)
            break
        except Exception:
            pass

    if anchor is None:
        if now_loc.date() == dia:
            anchor = now_loc
        else:
            apertura = int(getattr(settings, "HORARIO_APERTURA", 8))
            anchor = timezone.make_aware(datetime(dia.year, dia.month, dia.day, apertura, 0), tz)
    else:
        if now_loc.date() == dia and anchor < now_loc:
            anchor = now_loc

    # redondeo de anchor al siguiente múltiplo de intervalo
    step = int(getattr(settings, "RESERVA_INTERVALO_MIN", 15))
    bump = (step - (anchor.minute % step)) % step
    if bump:
        anchor = anchor + timedelta(minutes=bump)

    # ---------- unión de slots por mesa ----------
    # solo mesas con capacidad suficiente
    mesas = Mesa.objects.filter(sucursal=sucursal, capacidad__gte=party).only("id", "capacidad")
    all_slots = set()

    # si no hay mesas que soporten ese party, regresamos vacío (200)
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
            # Solo caemos al modo antiguo si el error es exactamente por el kw 'party'
            if "unexpected keyword argument 'party'" in str(e):
                return _slots_disponibles(m, dia)
            raise

    for m in mesas:
        try:
            for dt in _slots_for_mesa(m, dia, party):
                if dt >= anchor:
                    all_slots.add(dt)
        except Exception:
            # si una mesa da error, la ignoramos y seguimos con el resto
            continue

    futuros = sorted(all_slots)[:limit]

    # ---------- formateo para UI ----------
    # compatibilidad Windows/Linux con %-I/%#I
    def _label_12h(dloc: datetime) -> str:
        fmt = "%#I:%M %p" if os.name == "nt" else "%-I:%M %p"
        try:
            return dloc.strftime(fmt).lower()
        except Exception:
            # fallback portable
            return dloc.strftime("%I:%M %p").lstrip("0").lower()

    def _fmt(dt):
        dloc = dt.astimezone(tz)
        return {"label": _label_12h(dloc), "value": dloc.strftime("%H:%M")}

    # duración estimada (según party y tu lógica)
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







@login_required
@require_POST
def reservar_auto(request, sucursal_id):
    tz = timezone.get_current_timezone()
    s = get_object_or_404(Sucursal, pk=sucursal_id, activo=True)

    fecha_str = (request.POST.get("fecha") or "").strip()   # YYYY-MM-DD
    hora_str  = (request.POST.get("hora")  or "").strip()   # HH:MM
    try:
        party = max(1, int((request.POST.get("party") or "2").strip()))
    except Exception:
        party = 2

    # parse datetime
    try:
        inicio = timezone.make_aware(datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M"), tz)
    except Exception:
        messages.error(request, "Horario inválido.")
        return redirect("reservas:sucursal_detalle", slug=s.slug)

    # anticipación mínima (si ya tienes helper, úsalo)
    now_loc = timezone.localtime()
    if inicio <= now_loc:
        messages.error(request, "Selecciona un horario futuro.")
        return redirect("reservas:sucursal_detalle", slug=s.slug)

    # cliente
    cliente, _ = Cliente.objects.get_or_create(
        user=request.user,
        defaults={"nombre": request.user.get_full_name() or request.user.username,
                  "email": request.user.email or ""},
    )

    # asignación
    mesa = asignar_mesa_automatica(s, inicio, party)
    if not mesa:
        messages.error(request, "No hay mesas disponibles para ese horario y tamaño de grupo.")
        return redirect("reservas:sucursal_detalle", slug=s.slug)

    # CREAR reserva
    dur_min = booking_total_minutes(inicio, party)
    reserva = Reserva.objects.create(
        cliente=cliente,
        mesa=mesa,
        estado=Reserva.PEND,
        fecha=inicio,
        num_personas=party,
    )

    # correo on_commit (si ya lo usas en otros flujos)
    try:
        from .emails import enviar_correo_reserva_confirmada
        enviar_correo_reserva_confirmada(reserva, bcc_sucursal=True)
    except Exception:
        pass

    return redirect("reservas:reserva_exito", reserva_id=reserva.id)




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



from django.utils import timezone
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Sucursal

@login_required
def reservar_slot(request, sucursal_id):
    """
    Muestra un formulario para pedir PERSONAS y HORA (editable).
    Usa la fecha que llega por querystring y una hora sugerida,
    pero el usuario puede cambiarla antes de enviar.
    """
    s = get_object_or_404(Sucursal, pk=sucursal_id, activo=True)

    fecha_str = (request.GET.get("fecha") or "").strip()  # YYYY-MM-DD
    hora_sugerida = (request.GET.get("hora") or "").strip()  # HH:MM (opcional)
    if not fecha_str:
        messages.error(request, "Selecciona una fecha válida.")
        return redirect("reservas:sucursal_detalle", slug=s.slug)

    contexto = {
        "sucursal": s,
        "fecha": fecha_str,
        "hora_sugerida": hora_sugerida,      # se mostrará en un <input type="time"> editable
        "party_default": 2,
        "cap_max": 12,
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
    q = request.GET.get("q", "")
    hoy = timezone.localdate()
    sucursales = (Sucursal.objects.annotate(reservas_hoy=Count("reservas", filter=Q(reservas__fecha=hoy))))
    if q:
        sucursales = sucursales.filter(
            Q(nombre__icontains=q) | Q(ciudad__icontains=q)
        )
    return render(request, "reservas/sucursales_grid.html", {
        "sucursales": sucursales,
        "q": q
    })



def store_locator(request):
    return render(request, "public/store_locator.html")


