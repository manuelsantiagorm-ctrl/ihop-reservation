# reservas/models_pais.py
from django.conf import settings
from django.db import models

class Pais(models.Model):
    iso2 = models.CharField(max_length=2, unique=True)  # MX, US, ES...
    nombre = models.CharField(max_length=80)

    class Meta:
        verbose_name = "País"
        verbose_name_plural = "Países"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.iso2})"


class ChainOwnerPaisRole(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roles_pais")
    pais = models.ForeignKey(Pais, on_delete=models.CASCADE, related_name="chainowners")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "pais")
        verbose_name = "Administrador País (ChainOwner)"
        verbose_name_plural = "Administradores País (ChainOwners)"

    def __str__(self):
        estado = "activo" if self.activo else "inactivo"
        return f"{self.user} → {self.pais.iso2} ({estado})"
