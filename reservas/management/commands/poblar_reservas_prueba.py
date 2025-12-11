from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from reservas.models import Sucursal, Mesa, Cliente, Reserva, booking_total_minutes


class Command(BaseCommand):
    help = "Crea muchas reservas de prueba (con choques) para testear el sistema."

    def add_arguments(self, parser):
        parser.add_argument(
            "--total",
            type=int,
            default=1200,
            help="Cantidad de reservas a crear (default: 1200)",
        )

    def handle(self, *args, **options):
        total_a_crear = options["total"]

        # 1) Sucursal
        sucursal = Sucursal.objects.first()
        if not sucursal:
            self.stdout.write(self.style.ERROR("⚠️ No hay sucursales creadas todavía."))
            return

        self.stdout.write(f"Usando sucursal: {sucursal} (ID: {sucursal.id})")

        # 2) Mesas
        mesas = list(Mesa.objects.filter(sucursal=sucursal))
        if not mesas:
            self.stdout.write("No hay mesas en esta sucursal, creando 10 mesas de prueba...")
            for i in range(1, 11):
                mesas.append(
                    Mesa.objects.create(
                        sucursal=sucursal,
                        numero=i,
                        capacidad=4 if i <= 6 else 6,
                        zona="interior",
                    )
                )
            self.stdout.write(self.style.SUCCESS(f"Mesas creadas: {len(mesas)}"))
        else:
            self.stdout.write(f"Mesas encontradas: {len(mesas)}")

        # 3) Clientes
        clientes = list(Cliente.objects.all())
        if len(clientes) < 50:
            faltan = 50 - len(clientes)
            self.stdout.write(f"Hay {len(clientes)} clientes, creando {faltan} más...")
            base = len(clientes) + 1
            for i in range(base, base + faltan):
                clientes.append(
                    Cliente.objects.create(
                        nombre=f"Cliente {i}",
                        email=f"cliente{i}@test.local",
                        telefono=f"555000{i:03d}",
                    )
                )
        self.stdout.write(f"Total clientes: {len(clientes)}")

        # 4) Generar reservas masivas
        tz = sucursal.tz()
        hoy_local = timezone.now().astimezone(tz).replace(
            hour=8, minute=0, second=0, microsecond=0
        )

        creadas = 0
        self.stdout.write("Creando reservas de prueba...")

        dia = 0
        slot_min = 0

        while creadas < total_a_crear:
            # Fecha/hora local (aware)
            base_local_aware = hoy_local + timedelta(days=dia, minutes=slot_min)
            # Naive para set_from_local (él le pone tz)
            base_local_naive = datetime(
                year=base_local_aware.year,
                month=base_local_aware.month,
                day=base_local_aware.day,
                hour=base_local_aware.hour,
                minute=base_local_aware.minute,
            )

            mesa = mesas[creadas % len(mesas)]
            cliente = clientes[creadas % len(clientes)]
            party = (creadas % 6) + 1  # ~1..7 personas

            dur_min = booking_total_minutes(base_local_aware, party)

            reserva = Reserva(
                sucursal=sucursal,
                mesa=mesa,
                cliente=cliente,
                num_personas=party,
                estado=Reserva.CONF,
                creada_por_staff=True,
                nombre_contacto=cliente.nombre,
                email_contacto=cliente.email,
                telefono_contacto=cliente.telefono,
            )
            # Esto setea fecha, local_inicio/fin, inicio_utc/fin_utc, local_service_date
            reserva.set_from_local(base_local_naive, dur_min)
            reserva.save()

            creadas += 1

            # Slots cada 15 min; cuando se llenan 14h, pasamos al día siguiente
            slot_min += 15
            if slot_min >= (14 * 60):  # 14h de operación
                slot_min = 0
                dia += 1

            if creadas % 100 == 0:
                self.stdout.write(f"  → {creadas} reservas creadas...")

        self.stdout.write(self.style.SUCCESS(f"✅ Reservas creadas: {creadas}"))
