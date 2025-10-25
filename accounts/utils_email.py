from django.conf import settings
from django.core.mail import send_mail


def send_otp_email(to_email: str, code: str):
    subject = "Tu código de verificación"
    message = (
        f"Tu código de verificación es: {code}\n\n"
        "Este código vence en "
        f"{getattr(settings, 'EMAIL_OTP_EXP_MINUTES', 15)} minutos."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [to_email])
