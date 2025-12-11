# ihop_system/adapters.py
from allauth.account.adapter import DefaultAccountAdapter


class CustomAccountAdapter(DefaultAccountAdapter):
    """
    Adapter global para Allauth.

    REGLA:
    - Siempre permite registro (signup), ya sea normal o social (Google).
    - Allauth se encarga de:
        * Si el email YA existe -> solo login.
        * Si el email NO existe -> crea usuario y entra.
    """

    def is_open_for_signup(self, request, sociallogin=None, **kwargs):
        # 🔥 Punto clave: NUNCA cerrar registro
        return True
