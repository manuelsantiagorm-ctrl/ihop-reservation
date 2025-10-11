# reservas/utils.py
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import Q

from django.core.mail import send_mail

from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model

from .models import Reserva, PerfilAdmin, Mesa

from datetime import datetime, time
from django.utils import timezone
from django.conf import settings
from .models import Reserva
# ---------------------------
# Reglas de vigencia/bloqueo
# ---------------------------
def _rango_vigencia(fecha):
    """
    Regresa (inicio, fin) de la reserva usando RESERVA_TOTAL_MINUTOS.
    """
    total_min = int(getattr(settings, "RESERVA_TOTAL_MINUTOS", 70))
    return fecha, fecha + timedelta(minutes=total_min)


def minutos_bloqueo_dinamico(dt):
    """
    Minutos de bloqueo según hora pico o baja.
    Requiere en settings:
      HORAS_PICO = [(6,10), (12,15), (18,21)]
      BLOQUEO_HORAS_PICO = 80
      BLOQUEO_HORAS_BAJAS = 70
    """
    hp = getattr(settings, "HORAS_PICO", [])
    bloqueo_pico = int(getattr(settings, "BLOQUEO_HORAS_PICO", 80))
    bloqueo_bajas = int(getattr(settings, "BLOQUEO_HORAS_BAJAS", 70))

    # Tomar hora local de dt (aware) o naive sin tz si viniera así
    h = dt.astimezone(timezone.get_current_timezone()).hour if timezone.is_aware(dt) else dt.hour
    es_pico = any(inicio <= h <= fin for (inicio, fin) in hp)
    return bloqueo_pico if es_pico else bloqueo_bajas


# ---------------------------
# Helpers de limpieza/permisos
# ---------------------------
def _purge_expired_holds() -> int:
    """
    CANCELA ÚNICAMENTE “holds” (estado = 'HOLD') más antiguos de 10 minutos.
    No toca reservas PEND, que se manejan con _auto_cancel_por_tolerancia.
    """
    cutoff = timezone.now() - timedelta(minutes=10)
    qs = Reserva.objects.filter(estado='HOLD', creado__lt=cutoff)
    return qs.update(estado='CANC')


def _puede_ver_sucursal(user, sucursal) -> bool:
    """
    Superuser: acceso total. Staff: solo su sucursal asignada.
    """
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.is_staff:
        try:
            perfil = PerfilAdmin.objects.get(user=user)
            return perfil.sucursal_asignada_id == sucursal.id
        except PerfilAdmin.DoesNotExist:
            return False
    return False


# ---------------------------
# Disponibilidad / Choques
# ---------------------------
def conflicto_y_disponible(mesa: Mesa, fecha):
    """
    Devuelve (hay_conflicto: bool, proxima_hora_disponible: datetime)

    Considera TODAS las reservas que solapan con el bloque [inicio, fin)
    y, si hay choque, regresa como 'próxima disponible' el mayor fin de
    todas ellas (no la primera), para que el mensaje sea correcto.
    """
    dur_min = int(getattr(settings, 'RESERVA_TOTAL_MINUTOS', 70))
    dur = timedelta(minutes=dur_min)

    inicio = fecha
    fin = fecha + dur

    # Un bloqueo (r) solapa si: r.fecha < fin  y  (r.fecha + dur) > inicio
    qs = (Reserva.objects
          .filter(mesa=mesa, estado__in=['PEND', 'CONF'])
          .order_by('fecha'))

    max_fin = None
    for r in qs:
        r_inicio = r.fecha
        r_fin = r.fecha + dur
        if r_inicio < fin and r_fin > inicio:  # hay solapamiento
            if max_fin is None or r_fin > max_fin:
                max_fin = r_fin

    if max_fin:
        # hay conflicto: la próxima hora disponible es cuando termine el último solape
        return True, max_fin

    # sin conflicto
    return False, fecha


# ---------------------------
# Auto-cancelación por tolerancia
# ---------------------------

def _email_de_reserva(r):
    return (getattr(r.cliente, "email", "") or getattr(r, "email_contacto", "")).strip()




def _local_date_range(dt_date):
    """
    Devuelve el rango [inicio_dia_local, fin_dia_local) timezone-aware
    para la fecha local dt_date.
    """
    tz = timezone.get_current_timezone()
    start_naive = datetime(dt_date.year, dt_date.month, dt_date.day, 0, 0, 0)
    end_naive   = start_naive + timedelta(days=1)
    return timezone.make_aware(start_naive, tz), timezone.make_aware(end_naive, tz)

def _overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end

def _bloques_ocupados_mesa(mesa, dt_date):
    """
    Devuelve intervalos ocupados [(ini, fin), ...] para esa mesa en esa fecha (local),
    considerando reservas PEND/CONF. Todos timezone-aware.
    """
    start_day, end_day = _local_date_range(dt_date)
    # Trae reservas de ese día
    qs = (Reserva.objects
          .filter(mesa=mesa, estado__in=['PEND', 'CONF'],
                  fecha__gte=start_day, fecha__lt=end_day)
          .order_by('fecha'))

    dur = timedelta(minutes=getattr(settings, 'RESERVA_TOTAL_MINUTOS', 70))
    bloques = []
    for r in qs:
        ini = r.fecha
        fin = r.fecha + dur
        bloques.append((ini, fin))
    return bloques

def _overlap(a_start, a_end, b_start, b_end) -> bool:
    """True si [a) y [b) se traslapan."""
    return a_start < b_end and b_start < a_end
def _ceil_to_step(dt: datetime, step_min: int) -> datetime:
    """Redondea dt hacia ARRIBA al siguiente múltiplo de step_min."""
    dt = dt.replace(second=0, microsecond=0)
    m = dt.minute
    resto = m % step_min
    if resto:
        dt += timedelta(minutes=(step_min - resto))
    return dt

def _slots_disponibles(mesa: Mesa, fecha_d):
    """
    Genera datetimes (aware) de inicio posibles para 'fecha_d' en la mesa dada.
    Filtra:
      - fuera de apertura/cierre
      - en el pasado (si fecha_d es hoy, con buffer y redondeo)
      - solapes con PEND/CONF
    """
    tz = timezone.get_current_timezone()
    dur_min = int(getattr(settings, "RESERVA_TOTAL_MINUTOS", 70))
    paso_min = int(getattr(settings, "RESERVA_PASO_MINUTOS", 15))  # si no lo tienes en settings, queda en 15
    buffer_min = int(getattr(settings, "RESERVA_BUFFER_MINUTOS", 10))

    # Horario del local (puedes tenerlos en settings)
    apertura_h = int(getattr(settings, "HORARIO_APERTURA", 8))
    cierre_h   = int(getattr(settings, "HORARIO_CIERRE", 22))

    inicio_jornada = timezone.make_aware(datetime.combine(fecha_d, time(apertura_h, 0)), tz)
    fin_jornada    = timezone.make_aware(datetime.combine(fecha_d, time(cierre_h,   0)), tz)

    # No podemos arrancar una reserva que termine después de cerrar
    fin_slot_max_inicio = fin_jornada - timedelta(minutes=dur_min)

    if inicio_jornada > fin_slot_max_inicio:
        return []  # no caben reservas ese día

    # Si es HOY, arrancamos desde ahora + buffer, redondeado al paso
    ahora = timezone.now().astimezone(tz)
    if fecha_d == ahora.date():
        inicio_minimo = _ceil_to_step(ahora + timedelta(minutes=buffer_min), paso_min)
        inicio = max(inicio_jornada, inicio_minimo)
    else:
        inicio = inicio_jornada

    # Iteramos slots
    slots = []
    cursor = inicio
    dur_td = timedelta(minutes=dur_min)

    while cursor <= fin_slot_max_inicio:
        slot_fin = cursor + dur_td

        # ¿Se solapa con alguna reserva existente?
        # Primero las que empiezan antes de que termine este slot
        qs = Reserva.objects.filter(
            mesa=mesa,
            estado__in=["PEND", "CONF"],
            fecha__lt=slot_fin,          # comienzan antes de que termine este slot
        ).order_by("fecha")

        solapa = False
        for r in qs:
            # Si esa reserva todavía sigue cuando inicia este slot => choque
            if (r.fecha + dur_td) > cursor:
                solapa = True
                break

        if not solapa:
            slots.append(cursor)

        cursor += timedelta(minutes=paso_min)

    return slots

def _esta_en_horas_pico(dt_local):
    for h_ini, h_fin in getattr(settings, "HORAS_PICO", []):
        if h_ini <= dt_local.hour < h_fin:
            return True
    return False

def anticipacion_minima_para(dt_local):
    """
    dt_local: datetime aware en la TZ local del restaurante.
    Devuelve los minutos de anticipación requeridos para esa hora.
    """
    base = int(getattr(settings, "RESERVA_ANTICIPACION_MIN", 20))
    pico = int(getattr(settings, "RESERVA_ANTICIPACION_MIN_PICO", base))
    return pico if _esta_en_horas_pico(dt_local) else base



def _auto_cancel_por_tolerancia(minutos: int = 6) -> int:
    """
    Cancela reservas PEND cuya hora programada + tolerancia ya pasó.
    Evita select_for_update para poder invocarse desde cualquier vista.
    """
    ahora = timezone.now()
    limite = ahora - timezone.timedelta(minutes=minutos)
    # No usamos select_for_update aquí (no es necesario para un simple update).
    # Si varias instancias lo corren a la vez, el update es idempotente.
    return (
        Reserva.objects
        .filter(estado="PEND", fecha__lte=limite)
        .update(estado="CANC")
    )

def generar_folio(reserva) -> str:
    """
    R-YYYYMMDD-ABC123 basado en la fecha local de la reserva.
    """
    f = reserva.fecha.astimezone(timezone.get_current_timezone())
    suf = secrets.token_hex(3).upper()  # 6 chars
    return f"R-{f:%Y%m%d}-{suf}"


def _is_peak(dt):
    """True si la hora local cae en horas pico o fin de semana (sáb/dom)."""
    tz = timezone.get_current_timezone()
    loc = dt.astimezone(tz)
    for h1, h2 in getattr(settings, "HORAS_PICO", []):
        if h1 <= loc.hour < h2:
            return True
    if loc.weekday() in (5, 6):  # 5=sábado, 6=domingo
        return True
    return False

def booking_total_minutes(dt, party=2):
    """
    Minutos de ocupación de mesa (orden, comer, pago, limpieza).
    90 min normal, 105 min pico; +15 min si grupo ≥ 5.
    """
    base = settings.RESERVA_DURACION_MIN_PICO if _is_peak(dt) else settings.RESERVA_DURACION_MIN_NORM
    if int(party or 2) >= 5:
        base += 15
    return int(base)



def _aware_or_now(dt):
    """Devuelve un datetime aware. Si dt es None, usa ahora local."""
    if dt is None:
        return timezone.localtime()
    # Si viene naive, hazlo aware en la TZ actual
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt

def _is_peak(dt):
    """
    Devuelve True si el datetime cae en horario pico.
    Acepta dt=None sin romper (usa 'ahora').
    Ajusta la regla de pico a tu negocio si es distinta.
    """
    dt = _aware_or_now(dt)
    # Ejemplo de regla: viernes-domingo 18:00–22:00
    wd = dt.weekday()  # 0=lunes ... 6=domingo
    is_weekend = wd in (4, 5, 6)  # vie/sáb/dom
    hour = dt.hour
    in_evening = 18 <= hour < 22
    return is_weekend and in_evening



def booking_total_minutes(inicio_dt, party: int) -> int:
    """
    Duración dinámica sugerida según tamaño de grupo.
    Ajusta a tu operación real si lo deseas.
    """
    party = int(party or 2)
    if party <= 4:
        return 70   # 60-75 típico
    if party <= 7:
        return 90
    return 120      # grupos grandes (8-12)

def _en_ventana_proteccion(inicio_dt) -> bool:
    """¿Aún estamos antes del release de mesas grandes?"""
    prot = int(getattr(settings, "PROTECCION_BIG", 90))
    ahora = timezone.localtime()
    return ahora < (inicio_dt - timedelta(minutes=prot))

def mesa_elegible_para_party(mesa, party: int, inicio_dt) -> bool:
    """
    Regla de asignación:
     - Siempre: capacidad >= party
     - Si mesa grande (cap >= BIG_CAP) y estamos en protección:
         permitir solo si desperdicio <= WASTE_MAX
     - Fuera de protección: permitir libremente
    """
    cap = int(getattr(mesa, "capacidad", 0) or 0)
    if cap < int(party or 1):
        return False

    big_cap = int(getattr(settings, "BIG_CAP", 8))
    waste_max = int(getattr(settings, "WASTE_MAX", 3))

    if cap < big_cap:
        return True

    # mesa grande:
    if not _en_ventana_proteccion(inicio_dt):
        return True  # ya liberadas

    waste = cap - party
    return waste <= waste_max

def checa_choque_reserva_o_bloqueo(mesa, inicio_dt, fin_dt, party: int, exclude_reserva_id=None):
    """
    True si EXISTE conflicto (reserva o bloqueo).
    Ahora permite excluir una reserva (útil al moverla de mesa).
    """
    from .models import Reserva, BloqueoMesa
    from django.db.models import Q

    res_qs = (Reserva.objects
              .filter(mesa=mesa, estado__in=["PEND", "CONF"])
              .only("id", "fecha", "num_personas", "liberada_en"))
    if exclude_reserva_id:
        res_qs = res_qs.exclude(id=exclude_reserva_id)

    for r in res_qs:
        r_ini = r.fecha
        r_fin = r.fin_efectivo(getattr(r, "num_personas", party) or party)
        if r_ini < fin_dt and r_fin > inicio_dt:
            return True

    bloq_qs = (BloqueoMesa.objects
               .filter(sucursal=mesa.sucursal)
               .filter(Q(mesa__isnull=True) | Q(mesa=mesa))
               .filter(inicio__lt=fin_dt, fin__gt=inicio_dt))
    return bloq_qs.exists()


def asignar_mesa_automatica(sucursal, inicio_dt, party: int):
    """
    Devuelve una mesa “mínima suficiente” respetando protección/waste,
    sin choques. None si no hay.
    """
    from .models import Mesa
    from django.db.models import Q
    party = int(party or 2)
    dur_min = booking_total_minutes(inicio_dt, party)
    fin_dt = inicio_dt + timedelta(minutes=dur_min)

    mesas = (Mesa.objects
             .filter(sucursal=sucursal, capacidad__gte=party)
             .order_by("capacidad", "numero", "id"))

    # Opcional: evita mesas bloqueadas si tu modelo tiene ese campo
    if hasattr(Mesa, "bloqueada"):
        mesas = mesas.filter(Q(bloqueada=False) | Q(bloqueada__isnull=True))

    for m in mesas:
        if not mesa_elegible_para_party(m, party, inicio_dt):
            continue
        # chequea en vivo si hay conflicto
        if not checa_choque_reserva_o_bloqueo(m, inicio_dt, fin_dt, party):
            return m
    return None


def mesas_disponibles_para_reserva(reserva, forzar: bool = False):
    """
    Devuelve lista de mesas candidatas ordenadas por:
      1) menor desperdicio
      2) menor capacidad
    Respeta protección/waste salvo que 'forzar' sea True.
    """
    from .models import Mesa
    from django.db.models import Q
    from django.conf import settings

    party = int(getattr(reserva, "num_personas", 2) or 2)
    inicio = reserva.fecha
    dur_min = booking_total_minutes(inicio, party)
    fin = inicio + timedelta(minutes=dur_min)

    big_cap = int(getattr(settings, "BIG_CAP", 8))
    waste_max = int(getattr(settings, "WASTE_MAX", 3))

    mesas = (Mesa.objects
             .filter(sucursal=reserva.mesa.sucursal, capacidad__gte=party)
             .order_by("capacidad", "numero", "id"))

    cands = []
    for m in mesas:
        # Elegibilidad por protección/waste (si no es forzado)
        if not forzar and not mesa_elegible_para_party(m, party, inicio):
            continue

        # Choques (excluyendo la propia reserva al mover)
        hay_conflicto = checa_choque_reserva_o_bloqueo(
            m, inicio, fin, party, exclude_reserva_id=reserva.id
        )
        if hay_conflicto:
            continue

        waste = int(m.capacidad) - party
        cands.append((waste, int(m.capacidad), m))

    cands.sort(key=lambda t: (t[0], t[1]))  # menor waste, luego menor capacidad
    return [m for _, __, m in cands]

def mover_reserva(reserva, nueva_mesa, forzar: bool = False):
    """
    Intenta mover la reserva a 'nueva_mesa'.
    Valida protección/waste/choques (a menos que forzar=True).
    Retorna (ok: bool, motivo: str).
    """
    party = int(getattr(reserva, "num_personas", 2) or 2)
    inicio = reserva.fecha
    dur_min = booking_total_minutes(inicio, party)
    fin = inicio + timedelta(minutes=dur_min)

    if not forzar and not mesa_elegible_para_party(nueva_mesa, party, inicio):
        return False, "La mesa no es elegible por protección o desperdicio."

    if checa_choque_reserva_o_bloqueo(
        nueva_mesa, inicio, fin, party, exclude_reserva_id=reserva.id
    ):
        return False, "La mesa tiene un conflicto en ese horario."

    # OK: mover
    reserva.mesa = nueva_mesa
    reserva.save(update_fields=["mesa"])
    return True, "Reserva reasignada correctamente."







# reservas/utils.py


def is_chain_owner(user) -> bool:
    """Dueño de cadena: ve TODO."""
    return bool(
        user.is_authenticated and (
            user.is_superuser or user.has_perm("reservas.manage_branches")
        )
    )

def sucursales_visibles_qs(user, Sucursal):
    """
    QS de sucursales que el usuario puede ver.
    - Dueño de cadena → todas
    - Staff normal   → solo donde es administrador
    - Otros          → vacío
    """
    if not user.is_authenticated:
        return Sucursal.objects.none()
    if is_chain_owner(user):
        return Sucursal.objects.all()
    return Sucursal.objects.filter(administradores=user).distinct()

def get_visible_object_or_404(user, model, **lookup):
    """
    Trae un objeto de un model relacionado a una sucursal respetando visibilidad.
    * Reglas:
      - Model tiene FK llamada 'sucursal' (Mesa, Bloqueo, Reserva, Horario, etc.)
      - Para Sucursal, llama directamente sucursales_visibles_qs
    """
    from reservas.models import Sucursal  # import local para evitar ciclos

    if model is Sucursal:
        qs = sucursales_visibles_qs(user, Sucursal)
    else:
        # Asumimos que el model tiene FK 'sucursal'
        if is_chain_owner(user):
            qs = model.objects.all()
        else:
            qs = model.objects.filter(sucursal__administradores=user)

    return get_object_or_404(qs, **lookup)
