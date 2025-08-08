from django.contrib import admin
from .models import Sucursal, Mesa, Cliente, Reserva, PerfilAdmin


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'direccion', 'codigo_postal', 'total_mesas')


@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ('numero', 'capacidad', 'sucursal', 'estado')
    list_filter  = ('sucursal',)


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'email', 'telefono')


@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    list_display = ['cliente', 'mesa', 'fecha', 'estado']
    list_filter = ['estado', 'fecha']


@admin.register(PerfilAdmin)
class PerfilAdminAdmin(admin.ModelAdmin):
    list_display = ('user', 'sucursal_asignada')
