# reservas/utils.py
from datetime import timedelta
from django.conf import settings
from .models import Reserva

def minutos_bloqueo_dinamico(inicio_dt):
    """
    Retorna minutos de bloqueo según si está en horas pico o bajas.
    """
    hora = inicio_dt.hour
    for inicio, fin in getattr(settings, "HORAS_PICO", []):
        if inicio <= hora <= fin:
            return getattr(settings, "BLOQUEO_HORAS_PICO", 80)
    return getattr(settings, "BLOQUEO_HORAS_BAJAS", 70)


def conflicto_y_disponible(mesa, inicio_dt):
    """
    Devuelve (conflicto: bool, hora_disponible: datetime|None) para esa mesa,
    usando bloqueo dinámico.
    """
    minutos_bloqueo = minutos_bloqueo_dinamico(inicio_dt)
    total = timedelta(minutes=minutos_bloqueo)
    fin_dt = inicio_dt + total

    candidatas = (Reserva.objects
                  .filter(mesa=mesa,
                          fecha__lt=fin_dt,
                          fecha__gt=inicio_dt - total))

    for r in candidatas:
        r_fin = r.fecha + total
        if r.fecha < fin_dt and r_fin > inicio_dt:
            return True, r_fin
    return False, None
