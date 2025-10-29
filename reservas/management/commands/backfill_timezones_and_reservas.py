# reservas/management/commands/backfill_timezones_and_reservas.py
from django.core.management.base import BaseCommand
from django.core.exceptions import FieldDoesNotExist, FieldError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timezone as dt_timezone

from zoneinfo import ZoneInfo
from reservas.models import Reserva, Sucursal  # ajusta si tu app/modelos tienen otro path


class Command(BaseCommand):
    help = (
        "Backfill de campos de tiempo en reservas históricas:\n"
        "- Completa inicio_utc/fin_utc desde local_inicio/local_fin y viceversa\n"
        "- Ajusta local_service_date en hora local de la sucursal\n"
        "Soporta: --dry-run, --only-missing, filtros por país/sucursal/fechas y tamaño de lote."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="No guarda cambios, solo muestra resumen.")
        parser.add_argument("--only-missing", action="store_true",
                            help="Procesa solo reservas con campos faltantes (utc o local).")
        parser.add_argument("--batch-size", type=int, default=500, help="Tamaño de lote por transacción (default 500).")
        parser.add_argument("--limit", type=int, default=None, help="Máximo de registros a procesar.")
        parser.add_argument("--country", type=str, default=None, help="Filtra por país (nombre o código).")
        parser.add_argument("--sucursal-id", type=int, default=None, help="Filtra por ID de sucursal.")
        parser.add_argument("--date-from", type=str, default=None, help="ISO local date desde (YYYY-MM-DD) contra local_inicio o inicio_utc.")
        parser.add_argument("--date-to", type=str, default=None, help="ISO local date hasta (YYYY-MM-DD) contra local_inicio o inicio_utc.")
        parser.add_argument("--force", action="store_true",
                            help="Recalcula aunque existan ambos (utc y local). Úsalo con cuidado (haz backup).")

    def handle(self, *args, **opts):
        dry_run = opts["dry_run"]
        only_missing = opts["only_missing"]
        batch_size = opts["batch_size"]
        limit = opts["limit"]
        country = opts["country"]
        sucursal_id = opts["sucursal_id"]
        date_from = opts["date_from"]
        date_to = opts["date_to"]
        force = opts["force"]

        qs = (Reserva.objects
              .select_related("sucursal", "sucursal__pais")
              .order_by("id"))

        # ---- Filtros por país / sucursal ----
        if sucursal_id:
            qs = qs.filter(sucursal_id=sucursal_id)

        if country:
            # Detecta si Sucursal.pais es FK o CharField y arma filtro robusto
            suc_model = Reserva._meta.get_field("sucursal").remote_field.model
            try:
                pais_field = suc_model._meta.get_field("pais")
            except FieldDoesNotExist:
                self.stderr.write("El modelo Sucursal no tiene campo 'pais'. Ignorando --country.")
                pais_field = None

            country_filter = Q()
            used_paths = []

            if pais_field is not None and pais_field.is_relation:
                # FK a País → probar campos comunes
                pais_model = pais_field.remote_field.model
                candidate_fields = ["nombre", "codigo", "code", "iso2", "iso_code", "name"]
                for fname in candidate_fields:
                    try:
                        pais_model._meta.get_field(fname)
                        path_icontains = f"sucursal__pais__{fname}__icontains"
                        path_iexact = f"sucursal__pais__{fname}__iexact"
                        country_filter |= Q(**{path_icontains: country})
                        country_filter |= Q(**{path_iexact: country})
                        used_paths.extend([path_icontains, path_iexact])
                    except FieldDoesNotExist:
                        continue
            else:
                # pais es CharField (u otro no-relacional) en Sucursal
                country_filter = Q(sucursal__pais__icontains=country) | Q(sucursal__pais__iexact=country)
                used_paths = ["sucursal__pais__icontains", "sucursal__pais__iexact"]

            if country_filter:
                try:
                    qs = qs.filter(country_filter)
                    self.stdout.write(f"Filtro --country aplicado usando rutas: {', '.join(used_paths)}")
                except FieldError as e:
                    self.stderr.write(f"No se pudo aplicar filtro por país: {e}")
            else:
                self.stderr.write("No se construyó ningún filtro por país (revisa nombres de campos).")

        # ---- Filtros por fecha (aplicamos sobre lo disponible) ----
        if date_from:
            qs = qs.filter(Q(local_inicio__date__gte=date_from) | Q(inicio_utc__date__gte=date_from))
        if date_to:
            qs = qs.filter(Q(local_inicio__date__lte=date_to) | Q(inicio_utc__date__lte=date_to))

        # ---- Solo registros con campos faltantes ----
        if only_missing:
            qs = qs.filter(
                Q(inicio_utc__isnull=True) |
                Q(fin_utc__isnull=True) |
                Q(local_inicio__isnull=True) |
                Q(local_fin__isnull=True) |
                Q(local_service_date__isnull=True)
            )

        if limit:
            qs = qs[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No hay reservas que cumplan los filtros."))
            return

        self.stdout.write(
            f"Encontradas {total} reservas para procesar. "
            f"{'(dry-run)' if dry_run else ''} "
            f"{'(only-missing)' if only_missing else ''} "
            f"{'(force)' if force else ''}"
        )

        updated = 0
        unchanged = 0
        errors = 0

        buffer = []

        def process_buffer(buf):
            nonlocal updated, errors
            if not buf:
                return
            if dry_run:
                updated += len(buf)
                return
            try:
                with transaction.atomic():
                    for r in buf:
                        r.save(update_fields=[
                            "inicio_utc", "fin_utc", "local_inicio", "local_fin", "local_service_date"
                        ])
                        updated += 1
            except Exception as e:
                errors += len(buf)
                self.stderr.write(f"Error guardando lote de {len(buf)}: {e}")

        processed = 0
        for r in qs.iterator(chunk_size=batch_size):
            processed += 1

            tz_name = getattr(r.sucursal, "timezone", None)
            if not tz_name:
                self.stderr.write(f"[r#{r.id}] Sucursal sin timezone; omitiendo.")
                errors += 1
                continue

            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                self.stderr.write(f"[r#{r.id}] ZoneInfo inválido: {tz_name}; omitiendo.")
                errors += 1
                continue

            changed = False

            # 1) Si tenemos local pero falta utc, calcula utc
            if r.local_inicio and not r.inicio_utc:
                li = r.local_inicio if r.local_inicio.tzinfo else r.local_inicio.replace(tzinfo=tz)
                r.inicio_utc = li.astimezone(dt_timezone.utc)
                changed = True
            if r.local_fin and not r.fin_utc:
                lf = r.local_fin if r.local_fin.tzinfo else r.local_fin.replace(tzinfo=tz)
                r.fin_utc = lf.astimezone(dt_timezone.utc)
                changed = True

            # 2) Si tenemos utc pero falta local, calcula local
            if r.inicio_utc and not r.local_inicio:
                r.local_inicio = r.inicio_utc.astimezone(tz)
                changed = True
            if r.fin_utc and not r.local_fin:
                r.local_fin = r.fin_utc.astimezone(tz)
                changed = True

            # 3) Si ya existen ambos y pides --force, re-normaliza por si hubo desfases DST
            if force and r.local_inicio and r.inicio_utc:
                r.local_inicio = r.inicio_utc.astimezone(tz)
                changed = True
            if force and r.local_fin and r.fin_utc:
                r.local_fin = r.fin_utc.astimezone(tz)
                changed = True

            # 4) local_service_date coherente (si hay local_inicio)
            if r.local_inicio:
                lsd = r.local_inicio.astimezone(tz).date()
                if r.local_service_date != lsd:
                    r.local_service_date = lsd
                    changed = True

            if changed:
                buffer.append(r)
                if len(buffer) >= batch_size:
                    process_buffer(buffer)
                    buffer = []
            else:
                unchanged += 1

            if processed % 1000 == 0:
                self.stdout.write(f"Progresadas {processed}/{total}…")

        # Guardar residuo
        process_buffer(buffer)

        self.stdout.write(self.style.SUCCESS(
            f"Listo. Total={total} | Actualizadas={updated} | Sin cambios={unchanged} | Errores={errors} | "
            f"{'(dry-run)' if dry_run else ''}"
        ))
