# reservas/management/commands/asignar_chainowner_pais.py
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from reservas.models import Pais, ChainOwnerPaisRole

User = get_user_model()

class Command(BaseCommand):
    help = "Asigna o activa/desactiva un ChainOwner por país"

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Email del usuario")
        parser.add_argument("--iso2", required=True, help="Código de país (MX, US, ES, ...)")
        parser.add_argument("--inactivo", action="store_true", default=False, help="Marcar como inactivo")

    def handle(self, *args, **opts):
        email = opts["email"].strip().lower()
        iso2 = opts["iso2"].upper()
        inactivo = opts["inactivo"]

        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            raise CommandError(f"Usuario no encontrado: {email}")

        try:
            pais = Pais.objects.get(iso2=iso2)
        except Pais.DoesNotExist:
            raise CommandError(f"País no encontrado: {iso2}")

        role, _ = ChainOwnerPaisRole.objects.get_or_create(user=user, pais=pais)
        role.activo = not inactivo
        role.save(update_fields=["activo"])
        estado = "INACTIVO" if inactivo else "ACTIVO"
        self.stdout.write(self.style.SUCCESS(f"[OK] {email} → {iso2}: {estado}"))
