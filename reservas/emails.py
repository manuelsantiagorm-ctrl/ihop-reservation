# ==========================================================
# Archivo: reservas/emails.py
# ----------------------------------------------------------
# 📬 Módulo responsable de enviar correos de confirmación
# de reservas. Calcula la hora local de la SUCURSAL y,
# opcionalmente, muestra una equivalencia con la hora local
# del CLIENTE (por ejemplo: “Equivale a las 11:30 a. m. hora CDMX”).
# Compatible con reservas multi-país y multi-zona horaria.
# ==========================================================

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
    Devuelve la zona horaria (TZ) principal de la reserva (sucursal).
    Prioriza:
      1. reserva.mesa.sucursal.timezone
      2. reserva.mesa.sucursal.pais.timezone
      3. settings.TIME_ZONE
    """
    try:
        suc = getattr(reserva, "mesa", None) and getattr(reserva.mesa, "sucursal", None)
        if suc and getattr(suc, "timezone", None):
            return ZoneInfo(suc.timezone)
        if suc and getattr(suc, "pais", None) and getattr(suc.pais, "timezone", None):
            return ZoneInfo(suc.pais.timezone)
    except Exception:
        pass
    return timezone.get_current_timezone()


def _guess_cliente_tz(reserva):
    """
    Intenta deducir la TZ del cliente:
      - cliente.timezone (si existe)
      - perfil de usuario (si tiene)
      - settings.TIME_ZONE
    """
    cliente = getattr(reserva, "cliente", None)
    if cliente and hasattr(cliente, "timezone") and cliente.timezone:
        try:
            return ZoneInfo(cliente.timezone)
        except Exception:
            pass

    user = getattr(cliente, "user", None)
    if user and hasattr(user, "timezone") and user.timezone:
        try:
            return ZoneInfo(user.timezone)
        except Exception:
            pass

    return ZoneInfo(getattr(settings, "TIME_ZONE", "UTC"))


def enviar_correo_reserva_confirmada(reserva, *, bcc_sucursal: bool = False, reply_to: list[str] | None = None) -> int:
    """
    Envía el correo de confirmación al cliente (y opcionalmente en BCC a la sucursal).
    Incluye la hora local de la sucursal y, si aplica, la equivalencia en la TZ del cliente.
    Retorna 1 si se envió correctamente; 0 si hubo error.
    """
    try:
        cliente = getattr(reserva, "cliente", None)
        to_email = _normalize_email(getattr(cliente, "email", None))
        if not to_email:
            logger.warning("Reserva %s sin email de cliente; no se envía confirmación.", getattr(reserva, "id", "?"))
            return 0

        folio = getattr(reserva, "folio", "") or ""
        subject = f"Reserva confirmada · {folio}".strip()

        # --- Determinar zonas horarias ---
        tz_sucursal = _tz_for_reserva(reserva)
        tz_cliente = _guess_cliente_tz(reserva)

        # --- Base datetime (local_inicio o UTC) ---
        dt = getattr(reserva, "inicio_utc", None) or getattr(reserva, "local_inicio", None)
        if not dt:
            dt = getattr(reserva, "fecha", None)
        if not dt:
            logger.warning("Reserva %s sin fecha/hora válida.", reserva.id)
            return 0

        # --- Convertir a ambas zonas ---
        dt_sucursal = timezone.localtime(dt, tz_sucursal)
        dt_cliente = dt_sucursal.astimezone(tz_cliente)

        # --- Formatos de texto ---
        fecha_txt = formats.date_format(dt_sucursal.date(), "DATE_FORMAT")
        hora_txt = dt_sucursal.strftime("%I:%M %p").lstrip("0").lower()

        personas = getattr(reserva, "personas", None) or getattr(reserva, "num_personas", None) or 1
        sucursal = getattr(getattr(reserva, "mesa", None), "sucursal", None)

        mostrar_equivalencia = tz_sucursal.key != tz_cliente.key

        # --- Contexto para plantillas ---
        ctx = {
            "cliente": cliente,
            "reserva": reserva,
            "sucursal": sucursal,
            "fecha_txt": fecha_txt,
            "hora_txt": hora_txt,
            "personas": personas,
            "dt_sucursal": dt_sucursal,
            "dt_cliente": dt_cliente,
            "mostrar_equivalencia": mostrar_equivalencia,
            "tz_label_sucursal": getattr(getattr(sucursal, "pais", None), "nombre", None)
                or getattr(sucursal, "timezone", "Local"),
            "tz_label_cliente": tz_cliente.key.split("/")[-1].replace("_", " "),
        }

        # --- Render de plantillas ---
        try:
            body_html = render_to_string("emails/reserva_confirmada.html", ctx)
            body_txt = render_to_string("emails/reserva_confirmada.txt", ctx)
        except TemplateDoesNotExist:
            logger.exception("Plantilla faltante, usando fallback texto.")
            body_html = None
            body_txt = (
                f"Tu reserva {folio} ha sido confirmada para {fecha_txt} a las {hora_txt} "
                f"(hora local de la sucursal)."
            )

        # --- Configuración de envío ---
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None)
        if not from_email:
            logger.warning("DEFAULT_FROM_EMAIL no está configurado.")

        bcc = None
        if bcc_sucursal:
            suc_email = _normalize_email(getattr(sucursal, "email", None)) if sucursal else ""
            if suc_email:
                bcc = [suc_email]

        # --- Construcción del mensaje ---
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
        logger.info(
            "Confirmación enviada a %s (reserva=%s, folio=%s) -> %s",
            to_email, getattr(reserva, "id", "?"), folio, sent
        )
        return int(bool(sent))

    except Exception as e:
        logger.exception("Error enviando confirmación (reserva=%s): %s", getattr(reserva, "id", "?"), e)
        return 0
