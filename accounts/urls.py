# accounts/urls.py
from django.urls import path
from .views import SignupStartView, VerifyEmailView, ResendOTPView

app_name = "accounts"

urlpatterns = [
    path("signup/", SignupStartView.as_view(), name="signup_start"),
    path("verify-email/", VerifyEmailView.as_view(), name="verify_email"),
    path("resend-otp/", ResendOTPView.as_view(), name="resend_otp"),

    # (opcional) Aliases en español PERO bajo /accounts/...
    # path("cuentas/registro/",  RedirectView.as_view(pattern_name="accounts:signup_start", permanent=False)),
    # path("cuentas/verificar/", RedirectView.as_view(pattern_name="accounts:verify_email", permanent=False)),
]
