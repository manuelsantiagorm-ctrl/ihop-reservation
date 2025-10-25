import logging
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils.html import strip_tags
from django.conf import settings
from django.utils import timezone, formats

try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None


logger = logging.getLogger("reservas.mail")


def _normalize_email(val: str | None) -> str:
    return (val or "").strip()


def _tz_for_reserva(reserva):
    """
    Devuelve la zona horaria (TZ) para la reserva.
    Si tu modelo tiene algo como reserva.mesa.sucursal.pais.tz = "America/Mexico_City",
    úsalo; si no, cae a la TZ actual de Django.
    """
    tzname = None
    try:
        # Ajusta el acceso si tu campo se llama distinto (por ejemplo sucursal.timezone)
        tzname = getattr(getattr(getattr(reserva, "mesa", None), "sucursal", None), "pais", None)
        tzname = getattr(tzname, "tz", None)
    except Exception:
        tzname = None

    if tzname and ZoneInfo:
        try:
            return ZoneInfo(tzname)
        except Exception:
            pass

    # Si no se encontró TZ específica, usar la del sistema Django
    return timezone.get_current_timezone()


def enviar_correo_reserva_confirmada(reserva, *, bcc_sucursal: bool = False, reply_to: list[str] | None = None) -> int:
    """
    Envía el correo de confirmación al cliente (y opcionalmente en BCC a la sucursal).
    Retorna 1 si el backend reporta enviado, 0 si no se envió.
    Lanza excepción sólo si deseas fallar duro; por defecto captura y loguea.
    """
    try:
        cliente = getattr(reserva, "cliente", None)
        to_email = _normalize_email(getattr(cliente, "email", None))
        if not to_email:
            logger.warning("Reserva %s sin email de cliente; no se envía confirmación.", getattr(reserva, "id", "?"))
            return 0

        folio = getattr(reserva, "folio", "") or ""
        subject = f"Reserva confirmada · {folio}".strip()

        # ▼ NUEVO: calcula hora local y valores formateados
        tz = _tz_for_reserva(reserva)

        # Intenta usar reserva.local_inicio si existe; si no, cae a reserva.inicio o reserva.fecha
        dt = getattr(reserva, "local_inicio", None) or getattr(reserva, "inicio", None) or getattr(reserva, "fecha", None)
        if dt:
            dt_loc = timezone.localtime(dt, tz)
            fecha_txt = formats.date_format(dt_loc.date(), "DATE_FORMAT")
            hora_txt = dt_loc.strftime("%H:%M")
        else:
            fecha_txt = ""
            hora_txt = ""

        personas = getattr(reserva, "personas", None) or getattr(reserva, "num_personas", None) or 1
        sucursal = getattr(getattr(reserva, "mesa", None), "sucursal", None)

        # Contexto para las plantillas de correo
        ctx = {
            "cliente": cliente,
            "reserva": reserva,
            "sucursal": sucursal,
            "fecha_txt": fecha_txt,
            "hora_txt": hora_txt,
            "personas": personas,
        }

        # Render seguro de plantillas
        try:
            body_html = render_to_string("emails/reserva_confirmada.html", ctx)
            body_txt = render_to_string("emails/reserva_confirmada.txt", ctx)
        except TemplateDoesNotExist as e:
            logger.exception("Plantilla faltante para confirmación (%s). Usando solo texto plano.", e)
            body_html = None
            body_txt = f"Tu reserva {folio} ha sido confirmada."

        # from / reply-to
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        if not from_email:
            logger.warning("DEFAULT_FROM_EMAIL no está configurado. Configúralo en settings.py para mejor entregabilidad.")

        # BCC sucursal (si existe)
        bcc = None
        if bcc_sucursal:
            sucursal = getattr(getattr(reserva, "mesa", None), "sucursal", None)
            suc_email = _normalize_email(getattr(sucursal, "email", None)) if sucursal else ""
            if suc_email:
                bcc = [suc_email]

        # Construcción del mensaje
        msg = EmailMultiAlternatives(
            subject=subject,
            body=body_txt or strip_tags(body_html or ""),
            from_email=from_email,
            to=[to_email],
            bcc=bcc,
            reply_to=reply_to,
            headers={
                "X-App": "Reservas",
                "X-Reserva-ID": str(getattr(reserva, "id", "")),
                "X-Folio": folio,
            },
        )
        if body_html:
            msg.attach_alternative(body_html, "text/html")

        sent = msg.send(fail_silently=False)
        logger.info("Confirmación enviada a %s (reserva=%s, folio=%s) -> %s", to_email, getattr(reserva, "id", "?"), folio, sent)
        return int(bool(sent))

    except Exception as e:
        logger.exception("Error enviando confirmación (reserva=%s): %s", getattr(reserva, "id", "?"), e)
        return 0
