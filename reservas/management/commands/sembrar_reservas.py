
# reservas/management/commands/sembrar_reservas.py

from __future__ import annotations

from datetime import datetime, date, time
from typing import List, Tuple, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# ⚠️ Ajusta los imports a tus apps reales si el app_label no es "reservas"
from reservas.models import Reserva, Sucursal, Mesa, Cliente


def parse_turnos(text: str) -> List[Tuple[time, int]]:
    """
    Convierte una cadena como '16:00:2,16:15:3,17:00:4' en [(time(16,0),2), (time(16,15),3), ...]
    """
    out: List[Tuple[time, int]] = []
    text = (text or "").strip()
    if not text:
        return out
    for block in text.split(","):
        block = block.strip()
        # formatos admitidos: HH:MM:PAX  (p.ej. 16:00:2)
        try:
            hh, mm, pax = block.split(":")
            out.append((time(int(hh), int(mm)), int(pax)))
        except Exception:
            raise CommandError(f"Turno inválido: '{block}'. Usa HH:MM:PAX,HH:MM:PAX,…")
    return out


def get_or_create_seed_client() -> Cliente:
    email = "seed+reservas@ihop.local"
    defaults = {"nombre": "Seeder IHOP", "telefono": "0000000000"}
    cliente, _ = Cliente.objects.get_or_create(email=email, defaults=defaults)
    return cliente


def pick_mesa(sucursal: Sucursal) -> Optional[Mesa]:
    """
    Selecciona una mesa de la sucursal. Ajusta el filtro si tu modelo tiene capacidad, zona, etc.
    """
    return Mesa.objects.filter(sucursal=sucursal).order_by("id").first()


class Command(BaseCommand):
    help = "Siembra reservas de prueba para una fecha dada."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            required=True,
            help="Fecha destino en formato YYYY-MM-DD (hora local de la sucursal).",
        )
        parser.add_argument(
            "--sucursal",
            help="ID o slug de la sucursal. Si no se indica, se siembra en todas.",
        )
        parser.add_argument(
            "--turnos",
            default="16:00:2,16:10:3,16:15:4,17:00:3,18:00:2,19:00:4,20:00:3",
            help="Lista de turnos HH:MM:PAX separados por coma. Ej: '16:00:2,16:15:3'.",
        )
        parser.add_argument(
            "--estado",
            default=Reserva.PEND,
            choices=[Reserva.PEND, Reserva.CONF, Reserva.CANC, Reserva.NOSH],
            help="Estado inicial de las reservas creadas.",
        )
        parser.add_argument(
            "--duracion",
            type=int,
            default=90,
            help="Duración estimada en minutos (para materializar local_fin/fin_utc si usas esos campos).",
        )

    def handle(self, *args, **options):
        # --- Validar fecha ---
        try:
            fecha = date.fromisoformat(options["fecha"])
        except ValueError:
            raise CommandError("Formato de --fecha inválido. Usa YYYY-MM-DD.")

        turnos = parse_turnos(options["turnos"])
        if not turnos:
            raise CommandError("Debes indicar al menos un turno en --turnos.")

        # --- Resolver sucursales ---
        sucursal_arg = options.get("sucursal")
        sucursales_qs = Sucursal.objects.all()
        if sucursal_arg:
            # admitir id o slug
            try:
                suc = sucursales_qs.filter(pk=int(sucursal_arg)).first()
            except ValueError:
                suc = sucursales_qs.filter(slug=sucursal_arg).first()
            if not suc:
                raise CommandError(f"Sucursal '{sucursal_arg}' no encontrada.")
            sucursales = [suc]
        else:
            sucursales = list(sucursales_qs)
            if not sucursales:
                raise CommandError("No hay sucursales en la base de datos.")

        cliente_seed = get_or_create_seed_client()
        estado = options["estado"]
        duracion = options["duracion"]

        total_creadas = 0

        for suc in sucursales:
            # Necesitamos una mesa (FK obligatoria)
            mesa = pick_mesa(suc)
            if not mesa:
                self.stdout.write(self.style.WARNING(f"- Sucursal {suc} sin mesas: se omite."))
                continue

            # Intentar obtener tz desde método sucursal.tz(); si no existe, asumimos aware=fecha naive + tz fija
            try:
                tz = suc.tz()
            except Exception:
                tz = None  # guardaremos fecha tal cual; Django la convertirá si USE_TZ=True

            self.stdout.write(self.style.NOTICE(f">>> Sucursal: {getattr(suc, 'slug', suc.pk)}"))

            for hhmm, pax in turnos:
                # construir datetime local (naive) y, si podemos, volverlo aware con tz de la sucursal
                dt_local_naive = datetime.combine(fecha, hhmm)
                if tz:
                    dt_local = dt_local_naive.replace(tzinfo=tz)
                else:
                    dt_local = dt_local_naive  # lo guardará Django según tu configuración

                with transaction.atomic():
                    r = Reserva(
                        cliente=cliente_seed,
                        mesa=mesa,
                        sucursal=suc,
                        num_personas=pax,
                        estado=estado,
                    )

                    # Si tu modelo tiene set_from_local(dtime_naive, dur_minutes), úsalo para rellenar UTC/local
                    if hasattr(r, "set_from_local"):
                        r.set_from_local(dt_local_naive, duracion)
                    else:
                        # Compat: usa el campo legado 'fecha' directamente
                        r.fecha = dt_local

                    # Guarda (tu save() ya hace full_clean y autocompleta sucursal si venía por mesa)
                    r.save()

                    total_creadas += 1
                    self.stdout.write(f"   ✓ {r.folio} {r.fecha:%Y-%m-%d %H:%M} pax={pax}")

        self.stdout.write(self.style.SUCCESS(f"Listo. Reservas creadas: {total_creadas}"))
