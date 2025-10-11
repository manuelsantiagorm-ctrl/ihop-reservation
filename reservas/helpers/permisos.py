from django.http import Http404
from django.shortcuts import get_object_or_404
from ..models import Sucursal  # usa doble punto para subir un nivel

def user_can_manage_sucursal(user, sucursal: Sucursal) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    if user.groups.filter(name="ChainOwner").exists():
        return True
    return user.is_staff and sucursal.admins.filter(pk=user.pk).exists()

def assert_can_manage(request, sucursal_id: int) -> Sucursal:
    s = get_object_or_404(Sucursal, pk=sucursal_id)
    if not user_can_manage_sucursal(request.user, s):
        raise Http404()  # así nadie sabrá si existe o no
    return s
