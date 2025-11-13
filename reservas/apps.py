from django.apps import AppConfig

class ReservasConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "reservas"

    def ready(self):
        # Importa señales o modelos que no están en models.py para que Django los registre
        from . import models_menu 
        from . import models_orders# noqa


