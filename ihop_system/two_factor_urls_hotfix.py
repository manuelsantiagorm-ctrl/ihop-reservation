# ihop_system/two_factor_urls_hotfix.py
from django.urls import path
from django.views.generic import TemplateView

# Importa solo vistas que existen en todas (o casi todas) las versiones
from two_factor.views.core import LoginView, SetupView, QRGeneratorView, BackupTokensView
from two_factor.views.profile import ProfileView, DisableView

app_name = "two_factor"

urlpatterns = [
    # Rutas estándar del paquete:
    path("account/login/", LoginView.as_view(), name="login"),
    path("account/two_factor/setup/", SetupView.as_view(), name="setup"),
    path("account/two_factor/qrcode/", QRGeneratorView.as_view(), name="qr"),
    path(
        "account/two_factor/setup/complete/",
        TemplateView.as_view(template_name="two_factor/setup_complete.html"),
        name="setup_complete",
    ),
    path("account/two_factor/backup/tokens/", BackupTokensView.as_view(), name="backup_tokens"),
    path("account/two_factor/", ProfileView.as_view(), name="profile"),
    path("account/two_factor/disable/", DisableView.as_view(), name="disable"),
]
