# reservas/querysets.py
from __future__ import annotations

from datetime import datetime, time, timedelta
from django.db.models import QuerySet, Q
from django.utils import timezone


class ReservaQuerySet(QuerySet):
    """
    QuerySet helper para Reserva.
    Evita imports circulares (no importamos modelos aquí).
    """

    # Visibilidad por usuario
    def visible_for(self, user):
        """
        - Dueño de cadena (superuser o perm 'reservas.manage_branches'): ve todo
        - Staff: reservas de sucursales donde es administrador
        - Anónimo: nada
        Nota: usa relaciones hacia 'sucursal__administradores' y 'mesa__sucursal__administradores'
        para no importar modelos aquí y evitar ciclos.
        """
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if user.is_superuser or user.has_perm("reservas.manage_branches"):
            return self
        return (
            self.filter(
                Q(sucursal__administradores=user)
                | Q(mesa__sucursal__administradores=user)
            )
            .distinct()
        )

    # Filtros de tiempo
    def upcoming(self):
        """Próximas (>= ahora), orden cronológico."""
        now = timezone.now()
        return self.filter(fecha__gte=now).order_by("fecha")

    def for_day(self, d):
        """Todas las reservas de la fecha local 'd' (date)."""
        tz = timezone.get_current_timezone()
        start = timezone.make_aware(datetime.combine(d, time(0, 0)), tz)
        end = start + timedelta(days=1)
        return self.filter(fecha__gte=start, fecha__lt=end)

    def between(self, start, end):
        """Entre dos datetimes (inclusivo/exclusivo)."""
        return self.filter(fecha__gte=start, fecha__lt=end)

    # Estado
    def by_status(self, *estados):
        return self.filter(estado__in=estados)

    # Utilidades
    def for_branch(self, sucursal_id):
        """Por sucursal (FK directa) o vía mesa.sucursal, por si falta el campo."""
        return self.filter(Q(sucursal_id=sucursal_id) | Q(mesa__sucursal_id=sucursal_id))

    def for_client(self, cliente_id):
        return self.filter(cliente_id=cliente_id)
