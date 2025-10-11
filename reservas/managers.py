# reservas/managers.py
from django.db import models
from .utils import is_chain_owner

class OwnedBySucursalQuerySet(models.QuerySet):
    def visible_for(self, user):
        if not user.is_authenticated:
            return self.none()
        if is_chain_owner(user):
            return self
        return self.filter(sucursal__administradores=user)
