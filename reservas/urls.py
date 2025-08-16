from django.urls import path
from . import views

app_name = 'reservas'

urlpatterns = [
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),

    # Cliente
    path("seleccionar_sucursal/", views.seleccionar_sucursal, name="seleccionar_sucursal"),
    path("mesas/<int:sucursal_id>/", views.ver_mesas, name="ver_mesas"),
    path("reservar/<int:mesa_id>/", views.reservar, name="reservar"),
    path("mis_reservas/", views.mis_reservas, name="mis_reservas"),
    path("cancelar/<int:reserva_id>/", views.cancelar_reserva, name="cancelar_reserva"),

    # Admin
    path("admin/reservas/", views.admin_reservas, name="admin_reservas"),
    path("admin/sucursales/", views.admin_sucursales, name="admin_sucursales"),
    path("admin/sucursales/<int:sucursal_id>/mapa/", views.admin_mapa_sucursal, name="admin_mapa_sucursal"),
    path("admin/confirmar/<int:reserva_id>/", views.confirmar_reserva, name="confirmar_reserva"),
]
