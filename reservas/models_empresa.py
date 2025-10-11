from django.db import models

class Empresa(models.Model):
    nombre = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"

    def __str__(self):
        return self.nombre
