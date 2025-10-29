from django.shortcuts import redirect
from django.urls import reverse, resolve, NoReverseMatch

# --- IMPORTANTE: si el modelo TOTP no está, no rompemos ---
try:
    from django_otp.plugins.otp_totp.models import TOTPDevice
except Exception:
    TOTPDevice = None


# Solo deshabilita caché en páginas de auth (accounts/ y account/)
class NoCacheForAuthPagesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        p = request.path
        if p.startswith("/accounts/") or p.startswith("/account/"):
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response


TWO_FACTOR_NAMESPACE = "two_factor"

# Vistas de 2FA que NO deben ser interceptadas por el middleware de enforcement
EXEMPT_URL_NAMES = {
    f"{TWO_FACTOR_NAMESPACE}:login",
    f"{TWO_FACTOR_NAMESPACE}:setup",
    f"{TWO_FACTOR_NAMESPACE}:qr",
    f"{TWO_FACTOR_NAMESPACE}:setup_complete",
    f"{TWO_FACTOR_NAMESPACE}:backup_tokens",
    f"{TWO_FACTOR_NAMESPACE}:phone_setup",
    f"{TWO_FACTOR_NAMESPACE}:token",
    f"{TWO_FACTOR_NAMESPACE}:disable",
    f"{TWO_FACTOR_NAMESPACE}:profile",
}

# Prefijos que no interceptamos (estáticos, media, i18n, etc.)
EXEMPT_PREFIXES = (
    "/static/",
    "/media/",
    "/i18n/",
    "/jsi18n/",
    "/accounts/",       # allauth
    "/account/",        # two_factor hotfix montado en /account/
    "/admin/login",     # login admin
)


class StaffOTPRequiredMiddleware:
    """
    Exige OTP para usuarios staff:
      - Si ya está verificado -> deja pasar
      - Si NO está verificado:
          * Si tiene TOTP confirmado -> redirige a login OTP
          * Si NO tiene TOTP -> redirige a setup
    Evita loops al no interceptar rutas de auth/2FA.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        # No interceptar rutas exentas
        for prefix in EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            # Solo forzamos OTP a staff autenticado
            return self.get_response(request)

        # Si la ruta actual pertenece al namespace de 2FA, no redirigir
        try:
            match = resolve(path)
            url_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        except Exception:
            match = None
            url_name = None

        if url_name in EXEMPT_URL_NAMES or (match and match.namespace == TWO_FACTOR_NAMESPACE):
            return self.get_response(request)

        # ¿Está verificado por OTP?
        try:
            is_verified = user.is_verified()
        except Exception:
            # Fallback con request.otp_device que setea django-otp
            is_verified = getattr(request, "otp_device", None) is not None

        if is_verified:
            return self.get_response(request)

        # NO verificado: decidir si enviar a setup o a login OTP
        setup_url = _safe_reverse(f"{TWO_FACTOR_NAMESPACE}:setup", fallback="/account/two_factor/setup/")
        login_otp_url = _safe_reverse(f"{TWO_FACTOR_NAMESPACE}:login", fallback="/account/login/")

        has_confirmed_device = False
        if TOTPDevice is not None:
            try:
                has_confirmed_device = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
            except Exception:
                has_confirmed_device = False

        return redirect(login_otp_url if has_confirmed_device else setup_url)


def _safe_reverse(name: str, fallback: str) -> str:
    try:
        return reverse(name)
    except NoReverseMatch:
        return fallback



class RedirectSignupMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        if request.path.startswith("/auth/signup"):
            return redirect("accounts:signup_start")
        return self.get_response(request)


class RedirectNonStaffFromStaffURLs:
    """Si un usuario NO es staff y entra a /staff/, lo mandamos a seleccionar_sucursal."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ''
        if path.startswith('/staff/') and request.user.is_authenticated and not request.user.is_staff:
            return redirect(reverse('reservas:seleccionar_sucursal'))
        return self.get_response(request)
