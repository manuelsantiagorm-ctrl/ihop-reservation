# reservas/mixins.py
"""
Mixins de autorización/visibilidad para ChainOwner y Admins por país/sucursal.
- Usa Sucursal.objects.for_user(user) / visibles_para(user) para filtrar por usuario.
- Incluye utilidades por país (ChainOwnerPaisRole / user_allowed_countries) y por sucursal (FK directa o vía mesa).
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.db.models import QuerySet

from .models import Sucursal, ChainOwnerPaisRole

# Helpers opcionales del proyecto (si existen)
try:
    from .utils import is_chain_owner as _is_chain_owner
except Exception:
    def _is_chain_owner(user) -> bool:
        # Dueño de cadena equivalente: superuser o permiso global
        return getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches")

# Helpers de países (si existen)
try:
    from .utils_auth import user_allowed_countries as _user_allowed_countries
except Exception:
    def _user_allowed_countries(user):
        # Si no existe el helper, derivamos de ChainOwnerPaisRole
        if not getattr(user, "is_authenticated", False):
            return Sucursal.objects.none().values_list("pais", flat=True)
        if _is_chain_owner(user):
            # devolver un queryset sin filtrar no es viable aquí; que la vista no lo use
            return []
        return list(
            ChainOwnerPaisRole.objects.filter(user=user, activo=True).values_list("pais_id", flat=True)
        )


# ==============================================================================
# 1) Requerimiento de rol "chain owner" (superuser o permiso global)
# ==============================================================================

class ChainOwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Permite acceso a:
      - superuser
      - usuarios con permiso 'reservas.manage_branches'
      - usuarios del grupo "ChainOwner" (si existe)
    """
    def test_func(self):
        u = self.request.user
        return (
            u.is_authenticated
            and u.is_staff
            and (
                getattr(u, "is_superuser", False)
                or u.has_perm("reservas.manage_branches")
                or u.groups.filter(name="ChainOwner").exists()
            )
        )


# ==============================================================================
# 2) Filtro genérico por país (para modelos con campo pais/pais_id)
# ==============================================================================

class CountryScopeMixin:
    """
    Aplica filtro por países permitidos al usuario sobre un queryset arbitrario.
    Útil en vistas donde el model TIENE 'pais' o 'pais_id'.
    """
    def chain_scope(self, qs: QuerySet, country_field: str = "pais_id"):
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return qs.none()
        if _is_chain_owner(user):
            return qs
        # Origen de países: ChainOwnerPaisRole (o utils_auth si existe)
        pais_ids = list(
            ChainOwnerPaisRole.objects.filter(user=user, activo=True).values_list("pais_id", flat=True)
        )
        if not pais_ids:
            return qs.none()
        return qs.filter(**{f"{country_field}__in": pais_ids})


# ==============================================================================
# 3) Visibilidad por SUCURSAL (según reglas de negocio)
#    - Usa Sucursal.objects.for_user(request.user)
# ==============================================================================

class VisibleSucursalQuerysetMixin:
    """
    Para CBVs cuyo model es Sucursal.
    """
    model = Sucursal

    def get_queryset(self):
        # Nota: SucursalQuerySet expone for_user() y visibles_para()
        base = super().get_queryset()
        user = self.request.user
        if _is_chain_owner(user):
            return base
        if hasattr(Sucursal.objects, "for_user"):
            return Sucursal.objects.for_user(user)
        # Fallback (no debería ocurrir si ya tienes el manager)
        return Sucursal.objects.none()


class VisibleBySucursalFKMixin:
    """
    Para CBVs de modelos con FK directa 'sucursal' (p.ej. BloqueoMesa, MenuCategoria).
    Si tu FK se llama diferente, sobreescribe 'sucursal_field'.
    """
    sucursal_field = "sucursal"

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if _is_chain_owner(user):
            return qs
        visibles = Sucursal.objects.for_user(user)
        return qs.filter(**{f"{self.sucursal_field}__in": visibles})


class VisibleBySucursalViaMesaMixin:
    """
    Para CBVs de modelos que llegan a sucursal vía 'mesa__sucursal'
    (p.ej. un modelo Detalle o Reserva si no guardas sucursal directo).
    """
    mesa_field = "mesa"  # si la relación tiene otro nombre, sobreescribe en tu vista

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if _is_chain_owner(user):
            return qs
        visibles = Sucursal.objects.for_user(user)
        return qs.filter(**{f"{self.mesa_field}__sucursal__in": visibles})


# ==============================================================================
# 4) Objetos: validar que pertenecen a países permitidos (cuando el model tiene pais)
# ==============================================================================

class CountryScopedQuerysetMixin:
    """
    Filtra get_queryset() por países del usuario usando user_allowed_countries()
    (si tu modelo tiene FK 'pais').
    """
    country_field = "pais"  # o 'pais_id' si quieres filtrar por id

    def get_allowed_countries(self):
        return _user_allowed_countries(self.request.user)

    def get_queryset(self):
        qs = super().get_queryset()
        allowed = self.get_allowed_countries()
        if _is_chain_owner(self.request.user):
            return qs
        # soporta campo 'pais' (objeto) o 'pais_id' (id)
        field = self.country_field
        if field.endswith("_id"):
            return qs.filter(**{field + "__in": allowed})
        return qs.filter(**{field + "__in": allowed})


class CountryScopedObjectMixin:
    """
    Valida en get_object() que el objeto esté dentro de los países del usuario.
    Úsalo cuando el model tiene campo 'pais' o 'pais_id'.
    """
    country_attr = "pais"  # cambiar a 'pais_id' si necesitas comparar ids

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        user = self.request.user
        if _is_chain_owner(user):
            return obj

        allowed = set(_user_allowed_countries(user))
        # soporta attr 'pais' (objeto con id) o 'pais_id' (int)
        value = getattr(obj, self.country_attr, None)
        obj_country_id = getattr(value, "id", None) if value and hasattr(value, "id") else value
        if obj_country_id not in allowed:
            raise PermissionDenied("No puedes acceder a recursos de otro país.")
        return obj


# ==============================================================================
# 5) Protección de vistas/objetos por SUCURSAL (cuando la vista opera por pk de sucursal)
# ==============================================================================

class AssertUserCanManageSucursalMixin(LoginRequiredMixin):
    """
    Para vistas que reciben sucursal_id en la URL y deben validar acceso.
    Proporciona get_sucursal() y assert_user_can_manage_sucursal().
    """
    url_kwarg_sucursal = "sucursal_id"

    def get_sucursal(self) -> Sucursal:
        user = self.request.user
        qs = Sucursal.objects.for_user(user) if not _is_chain_owner(user) else Sucursal.objects.all()
        return get_object_or_404(qs, pk=self.kwargs[self.url_kwarg_sucursal])

    def assert_user_can_manage_sucursal(self, sucursal: Sucursal):
        user = self.request.user
        if _is_chain_owner(user):
            return
        # Si no entra en for_user, 404 para ocultar existencia
        if not Sucursal.objects.for_user(user).filter(pk=sucursal.pk).exists():
            raise Http404("Sucursal no encontrada o sin permisos.")


# ==============================================================================
# 6) Azúcar sintáctica: mixin de lista de sucursales staff
# ==============================================================================

class StaffSucursalesListMixin(VisibleSucursalQuerysetMixin, LoginRequiredMixin):
    """
    Úsalo directamente en tu ListView de sucursales staff:
      class StaffSucursalesListView(StaffSucursalesListMixin, ListView): ...
    """
    pass


# ==============================================================================
# Retro-compatibilidad de nombres (para imports existentes en tu proyecto)
# ==============================================================================

# Antes usabas ChainScopeMixin; ahora el nombre canónico es CountryScopeMixin.
class ChainScopeMixin(CountryScopeMixin):
    """Alias retro-compatible: mismo comportamiento que CountryScopeMixin."""
    pass

# En algunos módulos se importaban estos nombres:
# CountryRestrictedQuerysetMixin -> ahora VisibleSucursalQuerysetMixin (para Sucursal)
class CountryRestrictedQuerysetMixin(VisibleSucursalQuerysetMixin):
    """Alias retro-compatible: filtra listado de Sucursal visibles para el usuario."""
    pass

# CountryObjectPermissionMixin -> ahora CountryScopedObjectMixin (valida objeto por país)
class CountryObjectPermissionMixin(CountryScopedObjectMixin):
    """Alias retro-compatible: valida que el objeto pertenezca a países permitidos."""
    pass
