from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

urlpatterns = [
    # Admin
    path("admin/", admin.site.urls),

    # Tu app principal (con namespace)
    path("", include(("reservas.urls", "reservas"), namespace="reservas")),

    # Login/Logout personalizados en /login y /logout
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="reservas:home"), name="logout"),

    # Rutas estándar de auth (password reset/change) bajo /accounts/
    # No chocan con /login y /logout porque llevan el prefijo /accounts/
    path("accounts/", include("django.contrib.auth.urls")),
]
