
import random
import string
from datetime import timedelta, datetime, timezone as dt_tz
from contextlib import suppress

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from reservas.models import Sucursal, Mesa, Reserva
with suppress(ImportError):
    from reservas import utils

# ===== Parámetros =====
MAX_SUCURSALES = 5
HORAS_VENTANA = 10
RES_POR_HORA = 10
PROB_CHOQUE = 0.65
DUR_MIN = 50
DUR_MAX = 120
PARTY_MIN = 1
PARTY_MAX = 8
SEMILLA = 20251022
TAG_TEST = "TEST_LOAD"
CREA_MESAS_SI_NO_HAY = True

random.seed(SEMILLA)

# ===== Helpers =====
def get_first_field(model, candidates):
    names = {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}
    for c in candidates:
        if c in names:
            return c
    return None

def has_field(model, field_name):
    return field_name in [f.name for f in model._meta.get_fields()]

def pick_tz_for_sucursal(suc):
    import pytz
    tzname = None
    for attr in ("timezone", "timezone_str", "tz", "iana_timezone", "zona_horaria"):
        if hasattr(suc, attr) and getattr(suc, attr):
            tzname = getattr(suc, attr)
            break
    if not tzname:
        tzname = "America/Mexico_City"
    return pytz.timezone(tzname)

def ensure_basic_tables(suc):
    """
    Crea mesas automáticamente detectando campos:
    - nombre/name/codigo/label/slug (texto) o
    - numero/number/num/no (entero)
    - capacidad/capacity/asientos/plazas/seat_count (requerido)
    """
    if Mesa.objects.filter(sucursal=suc).exists():
        return
    if not CREA_MESAS_SI_NO_HAY:
        return

    name_field = get_first_field(Mesa, ('nombre','name','codigo','code','label','etiqueta','slug'))
    num_field  = get_first_field(Mesa, ('numero','number','num','nro','no'))
    cap_field  = get_first_field(Mesa, ('capacidad','capacity','cap','asientos','plazas','seat_count'))

    if not cap_field:
        print('⚠️  No encontré campo de capacidad en Mesa; no puedo crear mesas.')
        return

    capacities = [2,2,2,4,4,4,6,6,8,12]
    objs = []
    for i, cap in enumerate(capacities, start=1):
        kwargs = {'sucursal': suc, cap_field: cap}
        if name_field:
            kwargs[name_field] = f"M{i:02d}"
        elif num_field:
            kwargs[num_field] = i
        m = Mesa(**kwargs)
        for bf, val in (('activo', True), ('is_active', True), ('zona', 'interior'), ('area', 'interior')):
            if hasattr(m, bf):
                setattr(m, bf, val)
        objs.append(m)
    try:
        Mesa.objects.bulk_create(objs)
        print(f"  • Seed de mesas creado en {suc} ({len(objs)} mesas).")
    except Exception as e:
        print('⚠️  No pude sembrar mesas automáticamente:', e)

def random_phone():
    return "55" + "".join(random.choices(string.digits, k=8))

def choose_party_size():
    sizes = list(range(PARTY_MIN, PARTY_MAX+1))
    weights = [(8 if s in (2,3,4) else 4 if s in (5,6) else 2) for s in sizes]
    return random.choices(sizes, weights=weights, k=1)[0]

def overlaps_query(suc, mesa, start_utc, end_utc):
    if has_field(Reserva, "inicio_utc") and has_field(Reserva, "fin_utc"):
        qs = Reserva.objects.filter(sucursal=suc, mesa=mesa,
                                    inicio_utc__lt=end_utc, fin_utc__gt=start_utc)
    elif has_field(Reserva, "inicio") and has_field(Reserva, "fin"):
        qs = Reserva.objects.filter(sucursal=suc, mesa=mesa,
                                    inicio__lt=end_utc, fin__gt=start_utc)
    else:
        qs = Reserva.objects.filter(sucursal=suc, mesa=mesa)
    return qs

def set_reserva_times(reserva, suc, start_local, end_local, start_utc, end_utc):
    # Locales
    if has_field(Reserva, "local_inicio"):
        reserva.local_inicio = start_local
    if has_field(Reserva, "local_fin"):
        reserva.local_fin = end_local
    if has_field(Reserva, "local_service_date"):
        reserva.local_service_date = start_local.date()
    # UTC
    if has_field(Reserva, "inicio_utc"):
        reserva.inicio_utc = start_utc
    if has_field(Reserva, "fin_utc"):
        reserva.fin_utc = end_utc
    # Genéricos (por compatibilidad)
    if has_field(Reserva, "inicio"):
        reserva.inicio = start_utc
    if has_field(Reserva, "fin"):
        reserva.fin = end_utc

def set_reserva_identifiers(reserva, suc, personas):
    if has_field(Reserva, "telefono"):
        reserva.telefono = random_phone()
    if has_field(Reserva, "nombre"):
        reserva.nombre = f"{TAG_TEST} {personas}pax"
    for f in ("notas","comentarios","comentario","origen"):
        if has_field(Reserva, f):
            setattr(reserva, f, TAG_TEST)

def try_assign_with_utils(suc, start_local, end_local, personas):
    if "utils" not in globals():
        return None
    fun = getattr(utils, "asignar_mesa_automatica", None)
    if not callable(fun):
        return None
    try:
        mesa = fun(sucursal=suc, inicio_local=start_local, fin_local=end_local, personas=personas)
        if isinstance(mesa, (tuple, list)):
            mesa = mesa[0]
        return mesa
    except Exception:
        return None

def fallback_pick_mesa(suc, start_utc, end_utc, personas):
    cap_field = get_first_field(Mesa, ('capacidad','capacity','cap','asientos','plazas','seat_count'))
    qs = Mesa.objects.filter(sucursal=suc)
    if cap_field:
        qs = qs.filter(**{f"{cap_field}__gte": personas}).order_by(cap_field)
    else:
        qs = qs.order_by('id')
    mesas = list(qs)
    random.shuffle(mesas)
    for m in mesas:
        if not overlaps_query(suc, m, start_utc, end_utc).exists():
            return m
    return None

def first_choice_key(field):
    try:
        ch = getattr(field, 'choices', None) or []
        return ch[0][0] if ch else None
    except Exception:
        return None

def set_status_if_needed(reserva):
    cand = ('status','estado','estatus','state')
    names = {f.name: f for f in reserva._meta.get_fields() if getattr(f,'concrete',False)}
    for nm in cand:
        f = names.get(nm)
        if not f:
            continue
        val = first_choice_key(f) or 'confirmada'
        try:
            setattr(reserva, nm, val)
            return True
        except Exception:
            pass
    return False

def set_contact_if_needed(reserva):
    if hasattr(reserva, 'email') and not getattr(reserva, 'email', None):
        setattr(reserva, 'email', f"test{random.randint(1,99999)}@ihop.local")
    if hasattr(reserva, 'telefono') and not getattr(reserva, 'telefono', None):
        setattr(reserva, 'telefono', random_phone())

def try_fill_common_required(reserva):
    set_status_if_needed(reserva)
    set_contact_if_needed(reserva)

def get_party_field():
    return get_first_field(Reserva, (
        'personas','pax','comensales','cantidad','party_size',
        'num_personas','n_personas','guests','covers','diners'
    ))


def set_service_date(reserva, start_local):
    # Detecta y llena el campo de fecha requerido por el modelo
    for fld in (
        'fecha', 'fecha_reserva', 'fecha_servicio', 'service_date', 'reservation_date', 'local_service_date'
    ):
        if has_field(Reserva, fld):
            try:
                setattr(reserva, fld, start_local.date())
                break
            except Exception:
                pass


def run():
    sucursales = list(Sucursal.objects.all()[:MAX_SUCURSALES])
    if not sucursales:
        print("No hay sucursales. Crea al menos una y vuelve a intentar.")
        return

    total_intentos = 0
    total_creadas = 0
    total_choques = 0
    total_sin_mesa = 0

    print(f"Sembrando reservas en {len(sucursales)} sucursales...")
    for suc in sucursales:
        tz = pick_tz_for_sucursal(suc)
        ensure_basic_tables(suc)
        print(f">>> Sucursal: {suc} | TZ: {tz.zone}")

        now_local = datetime.now(tz).replace(minute=0, second=0, microsecond=0)
        horas = [now_local + timedelta(hours=h) for h in range(HORAS_VENTANA)]

        for base_local in horas:
            for _ in range(RES_POR_HORA):
                total_intentos += 1
                dur = random.randint(DUR_MIN, DUR_MAX)
                personas = choose_party_size()

                if random.random() < PROB_CHOQUE:
                    minute = random.choice((0,5,10,15,20))
                    total_choques += 1
                else:
                    minute = random.choice((0,10,20,30,40,50))

                start_local = base_local.replace(minute=minute)
                end_local = start_local + timedelta(minutes=dur)
                start_utc = start_local.astimezone(dt_tz.utc)
                end_utc = end_local.astimezone(dt_tz.utc)

                mesa = try_assign_with_utils(suc, start_local, end_local, personas)
                if mesa is None:
                    mesa = fallback_pick_mesa(suc, start_utc, end_utc, personas)
                if mesa is None:
                    total_sin_mesa += 1
                    continue

                try:
                    with transaction.atomic():
                        # kwargs dinámicos para el tamaño de grupo
                        res_kwargs = {'sucursal': suc, 'mesa': mesa}
                        party_field = get_party_field()
                        if party_field:
                            res_kwargs[party_field] = personas

                        reserva = Reserva(**res_kwargs)
                        set_reserva_times(reserva, suc, start_local, end_local, start_utc, end_utc)
                        set_reserva_identifiers(reserva, suc, personas)
                        try_fill_common_required(reserva)
                        set_service_date(reserva, start_local)

                        reserva.save()
                        total_creadas += 1
                except (ValidationError, IntegrityError) as e:
                    try:
                        msg = getattr(e, 'message_dict', None) or getattr(e, 'messages', None) or str(e)
                    except Exception:
                        msg = str(e)
                    print(f"⚠️  Error al crear reserva en {suc}: {msg}")
                except Exception as e:
                    print(f"⚠️  Error inesperado al crear reserva en {suc}: {e}")

    print("===== RESUMEN CARGA =====")
    print(f"Intentos totales:    {total_intentos}")
    print(f"Reservas creadas:    {total_creadas}")
    print(f"Intentos choque:     {total_choques}")
    print(f"Sin mesa disponible: {total_sin_mesa}")
    print("Marcador (notas/origen si existe):", TAG_TEST)
    print("Sugerencias: revisa admin/staff y tus analíticas.")

if __name__ == "__main__":
    run()
