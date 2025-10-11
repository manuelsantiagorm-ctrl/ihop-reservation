# reservas/email_utils.py
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string, get_template
from django.template import TemplateDoesNotExist
from django.utils import timezone
from datetime import timedelta
from types import SimpleNamespace
import logging

log = logging.getLogger(__name__)

def _get_sucursal(reserva):
    suc = getattr(reserva, "sucursal", None)
    if suc:
        return suc
    if getattr(reserva, "mesa", None) and getattr(reserva.mesa, "sucursal", None):
        return reserva.mesa.sucursal
    return SimpleNamespace(nombre="IHOP", direccion="")

def _reserva_to_local_range(reserva):
    inicio = timezone.localtime(reserva.fecha)
    fin = inicio + timedelta(minutes=90)
    return inicio, fin

def _build_ics_attachment_safe(reserva):
    """Adjunto .ics pero sin reventar si falta la librería."""
    try:
        from ics import Calendar, Event
    except Exception as e:
        log.warning("ICS no disponible: %s", e)
        return None

    suc = _get_sucursal(reserva)
    inicio, fin = _reserva_to_local_range(reserva)

    c = Calendar()
    e = Event()
    e.name = f"Reserva IHOP ({getattr(suc, 'nombre', 'IHOP')}) - {reserva.folio}"
    e.begin = inicio
    e.end = fin
    e.location = getattr(suc, "direccion", getattr(suc, "nombre", "IHOP"))
    e.description = (
        f"Folio: {reserva.folio}\n"
        f"Sucursal: {getattr(suc, 'nombre', 'IHOP')}\n"
        f"Mesa: {getattr(reserva.mesa, 'numero', '')}\n"
        f"Personas: {getattr(reserva, 'num_personas', getattr(reserva, 'personas', ''))}\n"
        f"Detalles: {settings.SITE_URL}/r/{reserva.folio}\n"
    )
    c.events.add(e)
    ics_bytes = str(c).encode("utf-8")
    return ("reserva.ics", ics_bytes, 'text/calendar; method=REQUEST; charset="utf-8"')

def _render_templates_safe(tipo, context):
    """Intenta html/txt; si faltan plantillas, genera fallback de texto."""
    html_body = None
    text_body = None
    try:
        html_body = render_to_string(f"emails/reserva_{tipo}.html", context)
    except TemplateDoesNotExist:
        html_body = None
    except Exception as e:
        log.exception("Error renderizando plantilla HTML: %s", e)
        html_body = None

    try:
        text_body = render_to_string(f"emails/reserva_{tipo}.txt", context)
    except TemplateDoesNotExist:
        text_body = None
    except Exception as e:
        log.exception("Error renderizando plantilla TXT: %s", e)
        text_body = None

    if not (html_body or text_body):
        # Fallback simple
        r = context["reserva"]; suc = context["sucursal"]; ini = context["inicio_local"]
        text_body = (
            f"¡Gracias por reservar en {getattr(suc,'nombre','IHOP')}!\n"
            f"Folio: {r.folio}\n"
            f"Mesa: {getattr(r.mesa,'numero','')}\n"
            f"Personas: {getattr(r,'num_personas','')}\n"
            f"Fecha y hora: {ini.strftime('%d/%m/%Y %H:%M')}\n"
            f"Detalle: {settings.SITE_URL}/r/{r.folio}\n"
        )
    return html_body, text_body

def send_reserva_email(reserva, tipo="confirmacion"):
    """
    tipo: 'confirmacion' | 'recordatorio'
    """
    suc = _get_sucursal(reserva)
    subject = {
        "confirmacion": f"✅ Reserva confirmada · {getattr(suc, 'nombre', 'IHOP')} · {reserva.folio}",
        "recordatorio": f"⏰ Recordatorio de reserva · {getattr(suc, 'nombre', 'IHOP')} · {reserva.folio}",
    }[tipo]

    to_email = []
    if getattr(reserva, "cliente", None) and getattr(reserva.cliente, "email", None):
        to_email = [reserva.cliente.email]
    if not to_email:
        log.warning("Reserva %s sin email de cliente -> no se envía", reserva.id)
        return "SKIP_NO_EMAIL"

    context = {
        "reserva": reserva,
        "sucursal": suc,
        "site_url": settings.SITE_URL,
        "inicio_local": timezone.localtime(reserva.fecha),
    }

    html_body, text_body = _render_templates_safe(tipo, context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body or "",
        from_email=settings.EMAIL_HOST_USER,   # mismo remitente que login Gmail
        to=to_email,
    )
    if html_body:
        msg.attach_alternative(html_body, "text/html")

    ics_tuple = _build_ics_attachment_safe(reserva)
    if ics_tuple:
        filename, payload, mimetype = ics_tuple
        msg.attach(filename, payload, mimetype)

    msg.send(fail_silently=False)
    return "OK"
