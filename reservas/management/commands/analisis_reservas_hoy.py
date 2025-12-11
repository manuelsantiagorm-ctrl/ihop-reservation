from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Count

from reservas.models import Reserva, Mesa, Sucursal


class Command(BaseCommand):
    help = "Muestra análisis detallado de las reservas del día actual (local_service_date)."

    def handle(self, *args, **options):
        # 1) Sucursal usada
        s = Sucursal.objects.first()
        if not s:
            self.stdout.write(self.style.ERROR("⚠️ No hay sucursales."))
            return

        hoy = timezone.localdate()
        self.stdout.write(f"Sucursal: {s} (ID {s.id})")
        self.stdout.write(f"Día local_service_date: {hoy}")
        self.stdout.write("=====================================")

        # 2) Todas las reservas de HOY en esa sucursal
        qs = Reserva.objects.filter(sucursal=s, local_service_date=hoy)

        total = qs.count()
        self.stdout.write(f"Total reservas HOY: {total}")
        if not total:
            return

        # 3) Conteo por estado
        self.stdout.write("\n➤ Estados (todas las reservas de hoy):")
        estados = (
            qs.values("estado")
              .annotate(c=Count("id"))
              .order_by("estado")
        )
        for e in estados:
            self.stdout.write(f"  - {e['estado']}: {e['c']}")

        # 4) Distribución por mesa
        self.stdout.write("\n➤ Reservas por mesa (hoy):")
        por_mesa = (
            qs.values("mesa__numero")
              .annotate(c=Count("id"))
              .order_by("mesa__numero")
        )
        for row in por_mesa:
            self.stdout.write(f"  - Mesa {row['mesa__numero']}: {row['c']} reservas")

        # 5) Rango horario de hoy
        primera = qs.order_by("local_inicio").first()
        ultima  = qs.order_by("local_inicio").last()
        self.stdout.write("\n➤ Rango horario de hoy:")
        self.stdout.write(f"  - Primera reserva: {primera.local_inicio} → {primera.local_fin}")
        self.stdout.write(f"  - Última reserva:  {ultima.local_inicio} → {ultima.local_fin}")

        # 6) Detectar SOLAPES (choques) por mesa
        self.stdout.write("\n➤ Solapes (choques) por mesa:")
        total_solapes = 0
        for mesa in Mesa.objects.filter(sucursal=s).order_by("numero"):
            m_qs = qs.filter(mesa=mesa).order_by("local_inicio")
            if not m_qs.exists():
                continue

            solapes_mesa = 0
            last_end = None

            for r in m_qs:
                if last_end and r.local_inicio < last_end:
                    # Esta reserva choca con la anterior
                    solapes_mesa += 1
                if r.local_fin and (last_end is None or r.local_fin > last_end):
                    last_end = r.local_fin

            total_solapes += solapes_mesa
            self.stdout.write(
                f"  - Mesa {mesa.numero}: {m_qs.count()} reservas, solapadas: {solapes_mesa}"
            )

        self.stdout.write(f"\nTotal de reservas solapadas (todas las mesas): {total_solapes}")

        # 7) Foco en las reservas del stress test (creada_por_staff=True)
        qs_staff = qs.filter(creada_por_staff=True)
        self.stdout.write("\n➤ Stress test (creada_por_staff=True):")
        self.stdout.write(f"  - Total hoy: {qs_staff.count()}")

        if qs_staff.exists():
            estados_staff = (
                qs_staff.values("estado")
                        .annotate(c=Count("id"))
                        .order_by("estado")
            )
            for e in estados_staff:
                self.stdout.write(f"    · {e['estado']}: {e['c']}")

            por_mesa_staff = (
                qs_staff.values("mesa__numero")
                        .annotate(c=Count("id"))
                        .order_by("mesa__numero")
            )
            self.stdout.write("  - Por mesa (solo stress test):")
            for row in por_mesa_staff:
                self.stdout.write(
                    f"    · Mesa {row['mesa__numero']}: {row['c']} reservas"
                )
