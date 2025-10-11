# reservas/signals.py
from __future__ import annotations

from datetime import timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Avg, Count
from django.db.models.signals import (
    pre_save, post_save, post_delete, post_migrate,
)
from django.dispatch import receiver
from django.utils import timezone
from django.core.mail import send_mail

from allauth.account.signals import user_signed_up, user_logged_in

# Modelos locales
from .models import (
    Sucursal,
    Mesa,
    Cliente,
    Reserva,
    BloqueoMesa,
    Review,
)

# Cache invalidation helper
from .cache_utils import invalidate_slots_for_sucursal_and_date


# ==============================================================================
# 1) SUCURSAL: Crear mesas por defecto en la creación (opcional, según settings)
# ==============================================================================
@receiver(post_save, sender=Sucursal)
def crear_mesas(sender, instance: Sucursal, created, **kwargs):
    """
    Al crear Sucursal, si hay configuración para mesas por defecto:
      - Usa instance.total_mesas si viene seteado; si no, settings.SUCURSAL_MESAS_DEFAULT.
      - Crea mesas 1..N con capacidad settings.MESA_CAPACIDAD_DEFAULT (por defecto 4)
    Evita duplicar si ya existen mesas.
    """
    if not created:
        return

    # Evitar duplicados
    if Mesa.objects.filter(sucursal=instance).exists():
        return

    # Determinar cantidad
    total = getattr(instance, "total_mesas", None)
    if total is None:
        total = getattr(settings, "SUCURSAL_MESAS_DEFAULT", 0)
    try:
        total = int(total)
    except Exception:
        total = 0

    if total <= 0:
        return

    capacidad_def = int(getattr(settings, "MESA_CAPACIDAD_DEFAULT", 4))

    with transaction.atomic():
        Mesa.objects.bulk_create(
            [Mesa(sucursal=instance, numero=i, capacidad=capacidad_def) for i in range(1, total + 1)],
            ignore_conflicts=True,
        )


# ==============================================================================
# 2) CLIENTE: Crear/asegurar perfil Cliente en signup/login (allauth)
# ==============================================================================
@receiver(user_signed_up)
def create_cliente_on_signup(request, user, **kwargs):
    Cliente.objects.get_or_create(
        user=user,
        defaults={
            "nombre": user.get_full_name() or user.username,
            "email": user.email or "",
        },
    )

@receiver(user_logged_in)
def ensure_cliente_on_login(request, user, **kwargs):
    Cliente.objects.get_or_create(
        user=user,
        defaults={
            "nombre": user.get_full_name() or user.username,
            "email": user.email or "",
        },
    )


# ==============================================================================
# 3) RESERVA: Emails por cambio de estado (CONF/CANC)
# ==============================================================================
def _email_destino_reserva(reserva: Reserva) -> str:
    """
    Email de contacto: prioriza Cliente.email; si no hay, usa email_contacto de la reserva.
    """
    email = (getattr(reserva.cliente, "email", "") or getattr(reserva, "email_contacto", "")).strip()
    return email

def _dt_local_reserva(reserva: Reserva):
    """
    Obtiene el datetime local de la reserva para comunicar (prioriza local_inicio si existe,
    luego fecha si ya la usas como aware local; como último recurso, convierte desde inicio_utc).
    """
    # 1) Campo local materializado
    dt = getattr(reserva, "local_inicio", None)
    if dt:
        return dt

    # 2) Campo legacy 'fecha' (si lo guardas aware local)
    dt = getattr(reserva, "fecha", None)
    if dt and timezone.is_aware(dt):
        return dt

    # 3) Convertir desde UTC a tz de la sucursal
    dt_utc = getattr(reserva, "inicio_utc", None)
    tzname = getattr(reserva.sucursal, "timezone", None) if reserva.sucursal_id else None
    tz = ZoneInfo(tzname or "UTC")
    if dt_utc:
        return dt_utc.astimezone(tz)
    return None

@receiver(pre_save, sender=Reserva)
def guardar_estado_anterior(sender, instance: Reserva, **kwargs):
    """
    Antes de guardar, almacena el estado previo en memoria para comparar en post_save.
    """
    if instance.pk:
        try:
            prev = Reserva.objects.get(pk=instance.pk)
            instance._prev_estado = prev.estado
        except Reserva.DoesNotExist:
            instance._prev_estado = None
    else:
        instance._prev_estado = None

@receiver(post_save, sender=Reserva)
def enviar_email_por_cambio_estado(sender, instance: Reserva, created, **kwargs):
    """
    Envía correo cuando el estado cambia:
      - a CONF (confirmada)
      - a CANC (cancelada manualmente)
    Nota: si hay otras rutas de cancelación masiva por .update(), manéjalas aparte.
    """
    prev = getattr(instance, "_prev_estado", None)
    nuevo = instance.estado
    if prev == nuevo:
        return

    email = _email_destino_reserva(instance)
    if not email:
        return

    dt_local = _dt_local_reserva(instance)
    fecha_txt = dt_local.strftime("%Y-%m-%d %H:%M") if dt_local else "(s/fecha)"
    try:
        mesa_txt = f"Mesa {instance.mesa.numero} - {instance.mesa.sucursal.nombre}"
    except Exception:
        mesa_txt = "Mesa"

    if nuevo == "CONF":
        asunto = "Confirmación de reserva - IHOP"
        cuerpo = (
            f"Tu reserva ha sido confirmada.\n\n"
            f"Reserva: #{instance.id}\n"
            f"{mesa_txt}\n"
            f"Hora: {fecha_txt}\n"
            f"¡Te esperamos!"
        )
        send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [email])

    elif nuevo == "CANC":
        asunto = "Reserva cancelada - IHOP"
        cuerpo = (
            f"Tu reserva ha sido cancelada.\n\n"
            f"Reserva: #{instance.id}\n"
            f"{mesa_txt}\n"
            f"Hora: {fecha_txt}\n"
            f"Si fue un error, puedes volver a reservar desde la app."
        )
        send_mail(asunto, cuerpo, settings.DEFAULT_FROM_EMAIL, [email])


# ==============================================================================
# 4) RATING SUCURSAL: Recalcular al crear/eliminar Review
# ==============================================================================
def _recompute_rating(sucursal: Sucursal):
    agg = Review.objects.filter(sucursal=sucursal).aggregate(avg=Avg("rating"), cnt=Count("id"))
    sucursal.rating = round((agg["avg"] or 0), 2)
    sucursal.reviews = agg["cnt"] or 0
    sucursal.save(update_fields=["rating", "reviews"])

@receiver(post_save, sender=Review)
def _rev_saved(sender, instance, **kwargs):
    _recompute_rating(instance.sucursal)

@receiver(post_delete, sender=Review)
def _rev_deleted(sender, instance, **kwargs):
    _recompute_rating(instance.sucursal)


# ==============================================================================
# 5) INVALIDACIÓN DE SLOTS (Reserva / BloqueoMesa)
# ==============================================================================
def _fecha_str_from_instance(obj) -> str | None:
    """
    Determina la fecha local (YYYY-MM-DD) para invalidar slots.
    Preferencias:
      - Reserva.local_service_date
      - Reserva.local_inicio.date() si existe
      - Reserva.fecha.date() si es aware
      - BloqueoMesa.inicio.date()
    """
    # Reserva
    if isinstance(obj, Reserva):
        if getattr(obj, "local_service_date", None):
            return obj.local_service_date.isoformat()
        if getattr(obj, "local_inicio", None):
            return obj.local_inicio.date().isoformat()
        if getattr(obj, "fecha", None) and timezone.is_aware(obj.fecha):
            return obj.fecha.date().isoformat()
        # Último recurso: UTC → local
        if getattr(obj, "inicio_utc", None):
            tzname = getattr(obj.sucursal, "timezone", None) if obj.sucursal_id else None
            tz = ZoneInfo(tzname or "UTC")
            return obj.inicio_utc.astimezone(tz).date().isoformat()
        return None

    # BloqueoMesa
    if isinstance(obj, BloqueoMesa):
        if getattr(obj, "inicio", None):
            return obj.inicio.date().isoformat()
        return None

    return None

def _sucursal_id_from_instance(obj) -> int | None:
    if isinstance(obj, Reserva):
        return obj.sucursal_id or (obj.mesa.sucursal_id if obj.mesa_id else None)
    if isinstance(obj, BloqueoMesa):
        return obj.sucursal_id or (obj.mesa.sucursal_id if obj.mesa_id else None)
    return None

@receiver([post_save, post_delete], sender=Reserva)
def invalidate_slots_on_reserva_change(sender, instance: Reserva, **kwargs):
    fecha_str = _fecha_str_from_instance(instance)
    sucursal_id = _sucursal_id_from_instance(instance)
    if fecha_str and sucursal_id:
        invalidate_slots_for_sucursal_and_date(sucursal_id, fecha_str)

@receiver([post_save, post_delete], sender=BloqueoMesa)
def invalidate_slots_on_bloqueo_change(sender, instance: BloqueoMesa, **kwargs):
    fecha_str = _fecha_str_from_instance(instance)
    sucursal_id = _sucursal_id_from_instance(instance)
    if fecha_str and sucursal_id:
        invalidate_slots_for_sucursal_and_date(sucursal_id, fecha_str)


# ==============================================================================
# 6) post_migrate: asegurar grupos y permisos base
# ==============================================================================
@receiver(post_migrate)
def _ensure_chainowner_group(sender, **kwargs):
    """
    Crea/asegura:
      - Permisos básicos para Sucursal
      - Grupo "ChainOwner" con esos permisos
      - Grupo "BranchAdmin" vacío (lo usas en tus vistas)
    """
    try:
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType

        ct = ContentType.objects.get_for_model(Sucursal)
        perms = [
            ("view_all_branches", "Puede ver todas las sucursales"),
            ("manage_branches", "Puede crear/editar/eliminar sucursales"),
            ("manage_branch_admins", "Puede crear/editar administradores de sucursal"),
        ]

        created_perms = []
        for codename, name in perms:
            p, _ = Permission.objects.get_or_create(
                codename=codename, name=name, content_type=ct
            )
            created_perms.append(p)

        g_owner, _ = Group.objects.get_or_create(name="ChainOwner")
        for p in created_perms:
            g_owner.permissions.add(p)

        Group.objects.get_or_create(name="BranchAdmin")
    except Exception:
        # Falla silenciosa en migraciones iniciales (por dependencias aún no listas)
        pass
