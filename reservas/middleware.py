# reservas/middleware.py
from django.shortcuts import redirect
from django.urls import reverse, resolve, NoReverseMatch

class NoCacheForAuthPagesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if getattr(request, "user", None) and request.user.is_authenticated:
            response["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
        return response


TWO_FACTOR_NAMESPACE = "two_factor"

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
EXEMPT_PREFIXES = ("/static/", "/media/", "/account/", "/admin/login")

class StaffOTPRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        for prefix in EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return self.get_response(request)

        try:
            match = resolve(path)
            url_name = f"{match.namespace}:{match.url_name}" if match.namespace else match.url_name
        except Exception:
            match = None
            url_name = None

        if url_name in EXEMPT_URL_NAMES or (match and match.namespace == TWO_FACTOR_NAMESPACE):
            return self.get_response(request)

        # ¿Ya verificó OTP?
        try:
            is_verified = user.is_verified()
        except Exception:
            is_verified = getattr(request, "otp_device", None) is not None

        if not is_verified:
            # 1º intento: namespace registrado
            try:
                return redirect(reverse(f"{TWO_FACTOR_NAMESPACE}:login"))
            except NoReverseMatch:
                # Fallback infalible
                return redirect("/account/login/")

        return self.get_response(request)
