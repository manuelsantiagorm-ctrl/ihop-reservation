# reservas/management/commands/health_tzapi.py
from django.core.management.base import BaseCommand
from reservas.utils_time import resolve_tz_from_latlng

class Command(BaseCommand):
    help = "Prueba la resolución de Time Zone API / fallback"

    def handle(self, *args, **kwargs):
        tz = resolve_tz_from_latlng(19.4326, -99.1332)  # CDMX
        if tz:
            self.stdout.write(self.style.SUCCESS(f"OK timezone={tz}"))
        else:
            self.stdout.write(self.style.ERROR("FAIL timezone could not be resolved"))
            raise SystemExit(1)
