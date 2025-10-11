# reservas/cache_utils.py
from django.core.cache import cache

SLOTS_TTL = 60  # segundos

def slots_key(sucursal_id, fecha_str, party, limit):
    # fecha_str formato "YYYY-MM-DD" (string)
    return f"slots:{sucursal_id}:{fecha_str}:{party}:{limit}"

def slots_get(sucursal_id, fecha_str, party, limit=10):
    return cache.get(slots_key(sucursal_id, fecha_str, party, limit))

def slots_set(sucursal_id, fecha_str, party, limit, data):
    cache.set(slots_key(sucursal_id, fecha_str, party, limit), data, timeout=SLOTS_TTL)

def slots_invalidate_prefix(prefix):
    # Si usas Redis: mejor usa delete_pattern (django-redis)
    try:
        client = cache.client.get_client(write=True)
        for k in client.scan_iter(match=f"{cache.key_prefix}:{prefix}*"):
            client.delete(k)
    except Exception:
        # Fallback: no hacer nada si backend no soporta patrón
        pass

def invalidate_slots_for_sucursal_and_date(sucursal_id, fecha_str):
    slots_invalidate_prefix(f"slots:{sucursal_id}:{fecha_str}")
