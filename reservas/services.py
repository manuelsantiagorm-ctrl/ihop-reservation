# reservas/services.py
from .cache_utils import slots_get, slots_set
from .utils import calcular_slots   # asumiendo que ya tienes esta función en utils.py

def get_slots_sucursal(sucursal_id, fecha_str, party, limit=10):
    cached = slots_get(sucursal_id, fecha_str, party, limit)
    if cached is not None:
        return cached

    # ---- calcula aquí con tus reglas de negocio ----
    slots = calcular_slots(sucursal_id, fecha_str, party, limit=limit)
    # ------------------------------------------------

    slots_set(sucursal_id, fecha_str, party, limit, slots)
    return slots
