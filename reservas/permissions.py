# reservas/permissions.py
from django.http import Http404
from django.apps import apps

def user_country_ids(user):
    """
    IDs de países que el usuario puede gestionar.
    - Superuser o manage_branches => None (sin restricción)
    - perfiladmin.paises + CountryAdminScope.is_active => lista de IDs
    - sin nada => []
    """
    if not getattr(user, "is_authenticated", False):
        return []

    # Dueño de cadena / permiso global
    if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
        return None

    ids = set()

    # Países por perfiladmin.paises
    perfil = getattr(user, "perfiladmin", None)
    if perfil and hasattr(perfil, "paises"):
        ids.update(perfil.paises.values_list("id", flat=True))

    # Países por CountryAdminScope (si existe el modelo)
    try:
        Scope = apps.get_model("reservas", "CountryAdminScope")
        ids.update(
            Scope.objects.filter(user=user, is_active=True).values_list("pais_id", flat=True)
        )
    except Exception:
        pass

    return list(ids)


def user_can_manage_sucursal(user, sucursal):
    """
    Determina si el usuario puede gestionar la sucursal indicada.
    Reglas: superuser / manage_branches / M2M / sucursal_asignada / países permitidos.
    """
    if not getattr(user, "is_authenticated", False):
        return False

    # Superuser o permiso global
    if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
        return True

    # Admin M2M explícito
    if sucursal.administradores.filter(pk=user.pk).exists():
        return True

    # Sucursal asignada directamente en perfil
    perfil = getattr(user, "perfiladmin", None)
    if perfil and getattr(perfil, "sucursal_asignada_id", None) == sucursal.id:
        return True

    # Alcance por países
    country_ids = user_country_ids(user)
    if country_ids is None:  # sin restricción
        return True
    return sucursal.pais_id in country_ids


def assert_user_can_manage_sucursal(user, sucursal):
    """
    Lanza 404 si el usuario no tiene permiso sobre la sucursal.
    (Usamos 404 para no revelar existencia de otras sucursales.)
    """
    if not user_can_manage_sucursal(user, sucursal):
        raise Http404("Sucursal no encontrada o sin permisos.")
