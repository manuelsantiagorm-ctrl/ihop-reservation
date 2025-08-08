from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Sucursal, Mesa

@receiver(post_save, sender=Sucursal)
def crear_mesas(sender, instance, created, **kwargs):
    if created:
        for i in range(1, instance.total_mesas + 1):
            Mesa.objects.create(
                sucursal=instance,
                numero=i,
                capacidad=4  # puedes cambiar según necesidades
            )
