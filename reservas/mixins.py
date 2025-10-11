# reservas/mixins.py
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.conf import settings

from .models import (
    Sucursal,
    ChainOwnerPaisRole,
)

# Si ya tienes estos helpers en utils.py, los reutilizamos.
# is_chain_owner(user) -> bool
# sucursales_visibles_qs(user, ModelOrQS=None) -> QS de Sucursal visibles
try:
    from .utils import is_chain_owner, sucursales_visibles_qs
except Exception:
    # Fallbacks seguros por si aún no existen (evitan romper import)
    def is_chain_owner(user) -> bool:
        return getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches")

    def sucursales_visibles_qs(user, _model=None):
        # Superuser ve todo
        if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
            return Sucursal.objects.all()
        # Sin helpers, retornamos none para evitar filtrar mal
        return Sucursal.objects.none()


# ==============================================================================
# Requerimientos de rol (dueño de cadena / superuser)
# ==============================================================================

class ChainOwnerRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Restringe acceso a:
      - superuser
      - usuarios con permiso 'reservas.manage_branches'
      - usuarios del grupo "ChainOwner" (si lo usas)
    """
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.is_staff and (
            getattr(u, "is_superuser", False)
            or u.has_perm("reservas.manage_branches")
            or u.groups.filter(name="ChainOwner").exists()
        )


# ==============================================================================
# Filtro POR PAÍS (ChainOwnerPaisRole)
#  - superuser    -> sin filtro
#  - chainowner   -> filtra por sus países (uno o varios)
#  - sin rol      -> queryset vacío
# ==============================================================================

# reservas/mixins.py

class ChainScopeMixin:
    """
    Filtra por país sólo si el usuario está autenticado y tiene roles por país.
    Si NO está autenticado, NO filtra (útil para pruebas públicas de API).
    """
    def chain_scope(self, qs, country_field="pais_id"):
        u = getattr(self.request, "user", None)
        if not u or not u.is_authenticated:
            return qs  # no restringir si no hay sesión (testing/public)
        if getattr(u, "is_superuser", False) or u.has_perm("reservas.manage_branches"):
            return qs
        from .models import ChainOwnerPaisRole
        pais_ids = list(
            ChainOwnerPaisRole.objects.filter(user=u, activo=True).values_list("pais_id", flat=True)
        )
        if not pais_ids:
            return qs.none()
        return qs.filter(**{f"{country_field}__in": pais_ids})

# ==============================================================================
# Visibilidad por SUCURSAL (según tus reglas de negocio existentes)
# ==============================================================================

class VisibleSucursalQuerysetMixin:
    """
    Para CBVs cuyo model es Sucursal.
    Aplica visibilidad según:
      - superuser / manage_branches -> todas
      - perfil asignado / administradores M2M -> visibles
    """
    model = Sucursal

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if is_chain_owner(user):
            return qs
        return sucursales_visibles_qs(user, self.model)


class VisibleBySucursalFKMixin:
    """
    Para CBVs de modelos con FK directa 'sucursal' (p.ej. BloqueoMesa, MenuCategoria).
    Si tu FK tiene otro nombre, sobreescribe 'sucursal_field'.
    """
    sucursal_field = "sucursal"

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if is_chain_owner(user):
            return qs
        visibles = sucursales_visibles_qs(user)
        return qs.filter(**{f"{self.sucursal_field}__in": visibles})


class VisibleBySucursalViaMesaMixin:
    """
    Para CBVs de modelos que llegan a sucursal vía 'mesa__sucursal' (p.ej. Reserva si no usas campo sucursal directo).
    """
    mesa_field = "mesa"  # si tu relación se llama diferente, sobreescribe

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if is_chain_owner(user):
            return qs
        visibles = sucursales_visibles_qs(user)
        return qs.filter(**{f"{self.mesa_field}__sucursal__in": visibles})
