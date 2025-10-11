# reservas/apps.py
from django.apps import AppConfig

class ReservacionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reservas"

    def ready(self):
        import reservas.signals  # noqa: F401


# reservas/apps.py







class ReservasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reservas"   # ⚠️ IMPORTANTE: debe apuntar al nombre del paquete (carpeta) real
    label = "reservas"  # explícito para evitar conflictos

    def ready(self):
        # Asegúrate de que este import exista y que el archivo signals.py esté correcto
        from . import signals  # noqa

