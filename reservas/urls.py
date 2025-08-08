from django.contrib import admin
from django.urls import path, include
from reservas import views as reservas_views  # ✅ solo reservas_views

urlpatterns = [
    # Panel de Django
    path('admin/', admin.site.urls),

    # Autenticación
    path('accounts/', include('django.contrib.auth.urls')),

    # Cliente
    path('', reservas_views.home, name='home'),
    path('register/', reservas_views.register, name='register'),
    path('mesas/<int:sucursal_id>/', reservas_views.ver_mesas, name='ver_mesas'),
    path('reservar/<int:mesa_id>/', reservas_views.reservar, name='reservar'),
    path('cancelar/<int:reserva_id>/', reservas_views.cancelar_reserva, name='cancelar_reserva'),
    path('mis-reservas/', reservas_views.mis_reservas, name='mis_reservas'),

    # Administrador
    path('admin/reservas/', reservas_views.admin_reservas, name='admin_reservas'),
    path('admin/confirmar-reserva/<int:reserva_id>/', reservas_views.confirmar_reserva, name='confirmar_reserva'),

    # Panel visual de mesas
    path('panel/mesas/', reservas_views.panel_mesas, name='panel_mesas'),
]
