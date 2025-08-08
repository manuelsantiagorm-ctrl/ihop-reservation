from django.apps import AppConfig

class ReservacionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'reservas'  # ✅ CORRECTO (NO debe decir 'reservaciones')

    def ready(self):
        import reservas.signals
