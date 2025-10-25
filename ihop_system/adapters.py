# ihop_system/adapters.py
from allauth.account.adapter import DefaultAccountAdapter

class CustomAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        """
        Cerramos el signup de Allauth (clientes usan tu flujo OTP en /accounts/).
        Los admins se crean desde el admin o por management commands.
        """
        return False

    def is_email_verification_required(self, request, email_address):
        """
        Si el usuario es staff o superuser, NO exigir verificación.
        Para el resto, mantener la política "mandatory".
        """
        user = email_address.user
        return not (user and (user.is_staff or user.is_superuser))
