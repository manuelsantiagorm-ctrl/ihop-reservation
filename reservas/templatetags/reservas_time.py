from django import template
from zoneinfo import ZoneInfo

register = template.Library()

@register.filter
def as_local(dt_utc, sucursal):
    """
    Convierte un datetime aware en UTC a la zona horaria IANA de la sucursal.
    Uso en template: {{ reserva.inicio_utc|as_local:reserva.sucursal|date:"d/m/Y H:i" }}
    """
    try:
        if dt_utc is None:
            return None
        tzname = getattr(sucursal, "timezone", None) or "UTC"
        return dt_utc.astimezone(ZoneInfo(tzname))
    except Exception:
        # Si algo falla, devolvemos el valor original para no romper la vista
        return dt_utc
