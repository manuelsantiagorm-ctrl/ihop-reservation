# reservas/apps.py
from django.apps import AppConfig

class ReservacionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reservas"

    def ready(self):
        import reservas.signals  # noqa: F401


# reservas/apps.py





# reservas/apps.py
# AppConfig de la app de reservas. Se encarga de registrar las señales en ready().


class ReservasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reservas"   # nombre del paquete (la carpeta de la app)
    label = "reservas"  # etiqueta única de la app

    def ready(self):
        # Importa las señales para que Django las registre al iniciar.
        # No mover este import a nivel de módulo para evitar import cycles.
        from . import signals  # noqa: F401
