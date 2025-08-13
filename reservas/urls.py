from django.urls import path
from . import views

app_name = 'reservas'  # importante para el namespace

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('reservar/<int:mesa_id>/', views.reservar, name='reservar'),
    path('cancelar/<int:reserva_id>/', views.cancelar_reserva, name='cancelar_reserva'),
    path('mis_reservas/', views.mis_reservas, name='mis_reservas'),
    path('seleccionar_sucursal/', views.seleccionar_sucursal, name='seleccionar_sucursal'),

    # ESTA ES LA RUTA QUE TE FALTABA RESOLVER
    path('mesas/<int:sucursal_id>/', views.ver_mesas, name='ver_mesas'),

    # (Opcionales) paneles internos
    path('panel-mesas/', views.panel_mesas, name='panel_mesas'),
    path('admin-reservas/', views.admin_reservas, name='admin_reservas'),
    path('confirmar-reserva/<int:reserva_id>/', views.confirmar_reserva, name='confirmar_reserva'),
]
