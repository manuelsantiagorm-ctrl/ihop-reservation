from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from reservas.models import Pais, Sucursal
from reservas.models import CountryAdminScope  # tu modelo de alcance país
from django.utils.text import slugify

User = get_user_model()

# TZ sugeridas por país (para sucursal de ejemplo)
DEFAULT_TZ = {
    "MX": "America/Mexico_City",
    "US": "America/New_York",      # EE.UU. tiene varias; cada sucursal usará la suya
    "CA": "America/Toronto",       # Canadá tiene varias
    "SA": "Asia/Riyadh",
    "KW": "Asia/Kuwait",
    "AE": "Asia/Dubai",
    "GT": "America/Guatemala",
    "PH": "Asia/Manila",
    "QA": "Asia/Qatar",
    "BH": "Asia/Bahrain",
    "EC": "America/Guayaquil"      # también existe Pacific/Galapagos
}
class Command(BaseCommand):
    help = "Crea administradores por país (ChainAdmins) y asigna su alcance."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-demo-branches",
            action="store_true",
            help="Crea también sucursales demo por país con su admin local.",
        )

    def handle(self, *args, **options):
        # aquí sigue el resto de tu código...
        print("Bootstrap ChainAdmin iniciado.")
        # ...



    @transaction.atomic
    def handle(self, *args, **options):

        super_admin_email = "administrador@ihop.com"  # ya existe, según nos comentaste
        self.stdout.write(self.style.SUCCESS("Bootstrap ChainAdmin iniciado."))

        countries = list(Pais.objects.all().order_by("nombre"))
        if not countries:
            self.stdout.write(self.style.ERROR(
                "No hay países. Primero ejecuta: loaddata reservas/fixtures/paises_iniciales.json"
            ))
            return

        for pais in countries:
            iso = (pais.iso2 or "").upper()
            if not iso:
                self.stdout.write(self.style.WARNING(f"Pais {pais.nombre} sin ISO2; se omite."))
                continue

            # 1) Country Admin por país
            email_country_admin = f"admin.{iso.lower()}@ihop.com"
            user_ca, created = User.objects.get_or_create(
                email=email_country_admin,
                defaults={
                    "username": email_country_admin,
                    "is_active": True,
                },
            )
            if created:
                user_ca.set_password("CambiaEsto123!")  # <--- cambia en producción
                user_ca.save()
                self.stdout.write(self.style.SUCCESS(f"Creado Country Admin: {email_country_admin}"))
            else:
                self.stdout.write(f"Country Admin ya existe: {email_country_admin}")

            # Asignar alcance país
            scope, scope_created = CountryAdminScope.objects.get_or_create(
                user=user_ca, pais=pais, defaults={"is_active": True}
            )
            if scope_created:
                self.stdout.write(self.style.SUCCESS(f"Asignado alcance a {email_country_admin}: {pais.nombre}"))

            # 2) Opcional: crear sucursal demo + admin de sucursal
            if options.get("with-demo-branches"):

                tz = DEFAULT_TZ.get(iso, "UTC")
                suc_name = f"IHOP - {pais.nombre} Centro"
                slug = slugify(f"ihop-{pais.nombre}-centro")

                sucursal, s_created = Sucursal.objects.get_or_create(
                    nombre=suc_name,
                    defaults=dict(
                        slug=slug,
                        direccion=f"Zona Centro, {pais.nombre}",
                        codigo_postal="00000",
                        pais=pais,
                        timezone=tz,
                        precio_nivel=1,
                        activo=True,
                    )
                )
                if s_created:
                    self.stdout.write(self.style.SUCCESS(f"Sucursal demo creada: {sucursal.nombre} [{tz}]"))
                else:
                    self.stdout.write(f"Sucursal demo ya existía: {sucursal.nombre}")

                # Crear admin de sucursal
                email_branch_admin = f"branch.{iso.lower()}@ihop.com"
                user_ba, ba_created = User.objects.get_or_create(
                    email=email_branch_admin,
                    defaults={"username": email_branch_admin, "is_active": True},
                )
                if ba_created:
                    user_ba.set_password("CambiaEsto123!")
                    user_ba.save()
                    self.stdout.write(self.style.SUCCESS(f"Creado Admin de Sucursal: {email_branch_admin}"))

                # Asignar M2M a la sucursal
                sucursal.administradores.add(user_ba)
                self.stdout.write(self.style.SUCCESS(
                    f"Asignado {email_branch_admin} como admin de {sucursal.nombre}"
                ))

        self.stdout.write(self.style.SUCCESS("Bootstrap ChainAdmin finalizado."))
