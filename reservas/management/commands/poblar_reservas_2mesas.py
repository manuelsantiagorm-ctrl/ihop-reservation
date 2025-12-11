# reservas/management/commands/poblar_reservas_2mesas.py
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from reservas.models import Sucursal, Mesa, Cliente, Reserva, booking_total_minutes


class Command(BaseCommand):
    help = "Crea 500 reservas en un solo día usando solo 2 mesas para probar colisiones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sucursal-id",
            type=int,
            help="ID de la sucursal a usar (por defecto la primera).",
        )
        parser.add_argument(
            "--total",
            type=int,
            default=500,
            help="Número de reservas a crear (default: 500).",
        )

    def handle(self, *args, **options):
        sucursal_id = options.get("sucursal_id")
        total_a_crear = options.get("total") or 500

        # 1) Obtener sucursal
        if sucursal_id:
            try:
                sucursal = Sucursal.objects.get(pk=sucursal_id)
            except Sucursal.DoesNotExist:
                self.stderr.write(self.style.ERROR(f"No existe sucursal con ID {sucursal_id}"))
                return
        else:
            sucursal = Sucursal.objects.first()
            if not sucursal:
                self.stderr.write(self.style.ERROR("⚠️ No hay sucursales creadas todavía."))
                return

        self.stdout.write(self.style.SUCCESS(f"Usando sucursal: {sucursal} (ID: {sucursal.id})"))

        # 2) Asegurar al menos 2 mesas en esta sucursal
        mesas = list(Mesa.objects.filter(sucursal=sucursal).order_by("numero"))
        if len(mesas) < 2:
            faltan = 2 - len(mesas)
            self.stdout.write(f"Solo hay {len(mesas)} mesas, creando {faltan} más...")
            num_base = (mesas[-1].numero if mesas else 0) + 1
            for i in range(num_base, num_base + faltan):
                mesas.append(
                    Mesa.objects.create(
                        sucursal=sucursal,
                        numero=i,
                        capacidad=4,
                        zona="interior",
                    )
                )
        # Nos quedamos solo con las 2 primeras
        mesas = mesas[:2]
        self.stdout.write(
            self.style.NOTICE(
                f"Usando SOLO estas 2 mesas para el stress test: "
                f"{mesas[0].numero} (ID {mesas[0].id}), {mesas[1].numero} (ID {mesas[1].id})"
            )
        )

        # 3) Asegurar suficientes clientes
        clientes = list(Cliente.objects.all())
        if len(clientes) < 50:
            faltan = 50 - len(clientes)
            self.stdout.write(f"Hay {len(clientes)} clientes, creando {faltan} más...")
            base = len(clientes) + 1
            for i in range(base, base + faltan):
                clientes.append(
                    Cliente.objects.create(
                        nombre=f"Cliente Stress {i}",
                        email=f"stress{i}@test.local",
                        telefono=f"555000{i:03d}",
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Total clientes disponibles: {len(clientes)}"))

        # 4) Generar reservas masivas en UN SOLO DÍA
        tz = sucursal.tz()
        target_date = timezone.now().astimezone(tz).date()  # hoy en la tz de la sucursal

        # Empezamos a las 12:00 del día target
        base_day_aware = timezone.datetime(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=12,
            minute=0,
            tzinfo=tz,
        )

        creadas = 0
        self.stdout.write(self.style.WARNING("Creando reservas de prueba (muchas colisiones)..."))

        for i in range(total_a_crear):
            # Alternamos entre las 2 mesas
            mesa = mesas[i % 2]
            cliente = clientes[i % len(clientes)]
            party = (i % 6) + 1  # 1..7 personas aprox

            # Queremos MUCHAS colisiones:
            # - Ponemos las reservas usando SOLO 60 slots (una hora)
            # - 500 reservas / 60 ≈ muchas reservas por mismo minuto/hora
            minutos_offset = (i % 60)  # 0..59 minutos
            base_local_aware = base_day_aware + timedelta(minutes=minutos_offset)

            # Naive para set_from_local (él pone tz)
            base_local_naive = datetime(
                year=base_local_aware.year,
                month=base_local_aware.month,
                day=base_local_aware.day,
                hour=base_local_aware.hour,
                minute=base_local_aware.minute,
            )

            # Duración usando tu helper
            dur_min = booking_total_minutes(base_local_aware, party)

            reserva = Reserva(
                sucursal=sucursal,
                mesa=mesa,
                cliente=cliente,
                num_personas=party,
                estado=Reserva.CONF,        # todas confirmadas
                creada_por_staff=True,      # para poder borrarlas fácil si quieres
                nombre_contacto=cliente.nombre,
                email_contacto=cliente.email,
                telefono_contacto=cliente.telefono,
            )
            # Esto setea fecha/local_inicio/local_fin/inicio_utc/fin_utc/local_service_date
            reserva.set_from_local(base_local_naive, dur_min)
            reserva.save()

            creadas += 1
            if creadas % 100 == 0:
                self.stdout.write(f"  → {creadas} reservas creadas...")

        self.stdout.write(self.style.SUCCESS(f"✅ Reservas creadas: {creadas}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Todas en el día {target_date} (local_service_date) "
                f"repartidas solamente en mesas {mesas[0].numero} y {mesas[1].numero}."
            )
        )
