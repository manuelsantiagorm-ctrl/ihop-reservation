# accounts/middleware.py
from django.shortcuts import redirect

class RedirectSignupMiddleware:
    """
    Redirige cualquier intento de /auth/signup/ al flujo OTP /accounts/signup/
    (evita que usen el registro de allauth).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/auth/signup"):
            return redirect("accounts:signup_start")
        return self.get_response(request)
