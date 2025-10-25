# reservas/utils_auth.py
from typing import Optional
from django.db.models import QuerySet
from django.contrib.auth.models import AbstractBaseUser

from .models import Pais, Sucursal

# Si tu modelo de alcance País-Usuario se llama distinto, ajusta el import:
# p. ej. from .models import CountryAdminScope
try:
    from .models import CountryAdminScope
except Exception:
    CountryAdminScope = None  # para evitar fallos si aún no existe


def user_allowed_countries(user: AbstractBaseUser) -> QuerySet[Pais]:
    """
    Devuelve un queryset de Pais que el usuario puede administrar como Country Admin.
    - Anónimo: ninguno
    - Superuser: todos
    - Country admin: los que tenga en CountryAdminScope
    - Otros: ninguno
    """
    if not getattr(user, "is_authenticated", False):
        return Pais.objects.none()

    if getattr(user, "is_superuser", False):
        return Pais.objects.all()

    if CountryAdminScope is None:
        # Si aún no tienes el modelo, nadie tiene alcance por país
        return Pais.objects.none()

    pais_ids = CountryAdminScope.objects.filter(user=user).values_list("pais_id", flat=True)
    return Pais.objects.filter(id__in=pais_ids)


def scope_sucursales_for(request, base_qs: Optional[QuerySet[Sucursal]] = None) -> QuerySet[Sucursal]:
    """
    Aplica el alcance por usuario a un queryset de Sucursal.
    - Superuser: sin filtro
    - Country admin: sólo sucursales de sus países
    - Branch admin (staff sin países): sólo sucursales donde es administrador
    - Usuario sin privilegios: none()
    """
    if base_qs is None:
        base_qs = Sucursal.objects.all()

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return base_qs.none()

    if user.is_superuser:
        return base_qs

    allowed = user_allowed_countries(user)
    if allowed.exists():
        return base_qs.filter(pais_id__in=allowed.values_list("id", flat=True))

    if user.is_staff:
        return base_qs.filter(administradores=user)

    return base_qs.none()
