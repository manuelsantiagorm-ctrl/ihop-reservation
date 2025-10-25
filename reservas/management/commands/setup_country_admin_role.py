# reservas/management/commands/setup_country_admin_role.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

# Ajusta a tus modelos reales
from reservas.models import Sucursal, Reserva, Mesa, Cliente  # etc.

PERM_MODELS = [Sucursal, Reserva, Mesa, Cliente]

class Command(BaseCommand):
    help = "Crea el grupo 'Country Admin' con permisos amplios"

    def handle(self, *args, **kwargs):
        group, _ = Group.objects.get_or_create(name="Country Admin")
        perms = []
        for mdl in PERM_MODELS:
            ct = ContentType.objects.get_for_model(mdl)
            perms += list(Permission.objects.filter(content_type=ct))  # add/change/delete/view
        group.permissions.set(perms)
        group.save()
        self.stdout.write(self.style.SUCCESS("Grupo 'Country Admin' listo con permisos amplios."))
