# reservas/utils_scope.py
from .models import ChainOwnerPaisRole

def chain_scope_queryset(request, qs, pais_field: str):
    u = request.user
    if u.is_superuser:
        return qs
    paises = list(
        ChainOwnerPaisRole.objects.filter(user=u, activo=True).values_list("pais_id", flat=True)
    )
    if not paises:
        return qs.none()
    return qs.filter(**{f"{pais_field}__in": paises})
