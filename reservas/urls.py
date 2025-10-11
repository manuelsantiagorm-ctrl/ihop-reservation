# reservas/urls.py
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required
from . import views
from .views_storelocator import store_locator, api_sucursales, api_sucursales_nearby

from .views_storelocator import (
    api_sucursales, api_sucursales_nearby, seleccionar_sucursal, store_locator)
# ChainAdmin: Admins de sucursal
from .views_chainadmin_admins import (
    ChainAdminAdminsListView, ChainAdminAdminsCreateView, ChainAdminAdminsUpdateView,
    ChainAdminAdminsPasswordView, ChainAdminAdminsToggleActiveView,
)
from .views_api import SucursalesJsonView, ReservaCreateFromLocalView

# ChainAdmin: Sucursales (CRUD)
from .views_chainadmin import (
    ChainAdminSucursalListView, ChainAdminSucursalCreateView,
    ChainAdminSucursalUpdateView, ChainAdminSucursalDeleteView,
)
from .views_chain_global import (
    ChainGlobalDashboardView,
    ChainGlobalRoleCreateView,          # si ya la tienes
    ChainGlobalRoleToggleActiveView,    # si ya la tienes
    CreateCountryAdminUserView,         # NUEVO
)

app_name = "reservas"

urlpatterns = [
    # ===== API pública existente =====
    path("api/sucursal/<int:sucursal_id>/slots/", views.api_slots_sucursal, name="api_slots_sucursal"),

    # ===== Público / cliente =====
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("perfil/", views.perfil, name="perfil"),
    path("mis_reservas/", views.mis_reservas, name="mis_reservas"),
    path("seleccionar_sucursal/", views.seleccionar_sucursal, name="seleccionar_sucursal"),
    path("reservar/<int:mesa_id>/", views.reservar, name="reservar"),

    # Disponibilidad (cliente)
    path("mesas/<int:mesa_id>/disponibilidad.json", views.disponibilidad_mesa, name="disponibilidad_mesa_json"),
    path("disponibilidad/mesa/<int:mesa_id>/", views.disponibilidad_mesa, name="disponibilidad_mesa"),

    # Flujo de reserva
    path("reserva/exito/<int:reserva_id>/", views.reserva_exito, name="reserva_exito"),
    path("reserva/<int:reserva_id>/confirmar/", views.confirmar_reserva, name="confirmar_reserva"),

    # ===== Store locator (NUEVO mapa público) =====
    path("sucursales/", views.store_locator, name="store_locator"),
    # (opcional) deja tu grid en otra ruta
    path("sucursales/grid/", views.sucursales_grid, name="sucursales_grid"),

    # ===== Staff (prefijo /staff/) =====
    # Sucursales
    path("staff/sucursales/", views.admin_sucursales, name="admin_sucursales"),
    path("staff/sucursales/nueva/", views.admin_sucursal_form, name="admin_sucursal_nueva"),
    path("staff/sucursales/<int:pk>/editar/", views.admin_sucursal_form, name="admin_sucursal_editar"),
    path("staff/sucursales/<int:sucursal_id>/contenido/", views.admin_sucursal_contenido, name="admin_sucursal_contenido"),
    path("staff/sucursal/<int:sucursal_id>/bloqueos/", views.admin_bloqueos, name="admin_bloqueos"),

    # Mapa y mesas
    path("staff/sucursal/<int:sucursal_id>/mapa/", views.admin_mapa_sucursal, name="admin_mapa_sucursal"),
    path("staff/mesa/<int:mesa_id>/", views.admin_mesa_detalle, name="admin_mesa_detalle"),
    path("staff/mesa/<int:mesa_id>/editar/", views.admin_mesa_editar, name="admin_editar_mesa"),
    path("staff/sucursal/<int:sucursal_id>/mesa/crear/", views.admin_mesa_crear, name="admin_mesa_crear"),

    # API de mesas
    path("staff/api/mesa/<int:mesa_id>/update/", views.admin_api_mesa_update, name="admin_api_mesa_update"),
    path("staff/api/mesa/<int:mesa_id>/pos/", views.admin_api_mesa_pos, name="admin_api_mesa_pos"),
    path("staff/api/mesa/create/", views.admin_api_mesa_create, name="admin_api_mesa_create"),
    path("staff/mesas/<int:mesa_id>/setpos/", views.admin_api_mesa_setpos, name="admin_api_mesa_setpos"),

    # API de recepción (drag node)
    path("staff/sucursal/<int:sucursal_id>/api/recepcion/pos/", views.admin_api_recepcion_pos, name="admin_api_recepcion_pos"),

    # Bloqueos de mesas
    path("staff/api/bloqueo/create/", views.admin_api_bloqueo_create, name="admin_api_bloqueo_create"),
    path("staff/api/bloqueo/list/", views.admin_api_bloqueo_list, name="admin_api_bloqueo_list"),
    path("staff/api/bloqueo/delete/", staff_member_required(views.admin_api_bloqueo_delete), name="admin_api_bloqueo_delete"),

    # Disponibilidad staff / agenda
    path("staff/disponibilidad/mesa/<int:mesa_id>/", views.admin_disponibilidad_mesa, name="admin_disponibilidad_mesa"),
    path("staff/agenda/mesa/<int:mesa_id>/", views.agenda_mesa, name="agenda_mesa"),
    path("staff/api/disponibilidad/", views.staff_api_disponibilidad, name="staff_api_disponibilidad"),
    path("staff/api/disponibilidad/json/", views.staff_disponibilidad_json, name="staff_disponibilidad_json"),

    # Reservas staff
    path("staff/reservas/", views.admin_reservas, name="admin_reservas"),
    path("staff/reservas/<int:reserva_id>/finalizar/", views.admin_finalizar_reserva, name="admin_finalizar_reserva"),
    path("staff/reservas/<int:reserva_id>/reasignar/", views.admin_reasignar_reserva, name="admin_reasignar_reserva"),
    path("staff/reserva/<int:reserva_id>/confirmar-llegada/", views.admin_confirmar_llegada, name="admin_confirmar_llegada"),

    # Mesas disponibles (vista general)
    path("staff/sucursal/<int:sucursal_id>/mesas/", views.ver_mesas, name="admin_mesas_disponibles"),

    # Detalle sucursal pública
    path("s/<slug:slug>/", views.sucursal_detalle, name="sucursal_detalle"),

    # Flujo de reserva para cliente
    path("sucursal/<int:sucursal_id>/reservar-slot/", views.reservar_slot, name="reservar_slot"),
    path("sucursal/<int:sucursal_id>/reservar-auto/", views.reservar_auto, name="reservar_auto"),

    # Atajos admin nativo
    path("admin-site/sucursales/", views.admin_site_sucursales, name="admin_site_sucursales"),
    path("admin-site/mesas/", views.admin_site_mesas, name="admin_site_mesas"),
    path("admin-site/reservas/", views.admin_site_reservas, name="admin_site_reservas"),

    # Health checks
    path("healthz/", views.healthz, name="healthz"),
    path("readyz/", views.readyz, name="readyz"),

    # ===== ChainAdmin — Administradores de sucursal =====
    path("chainadmin/admins/", ChainAdminAdminsListView.as_view(), name="chainadmin_admins"),
    path("chainadmin/admins/nuevo/", ChainAdminAdminsCreateView.as_view(), name="chainadmin_admin_nuevo"),
    path("chainadmin/admins/<int:user_id>/editar/", ChainAdminAdminsUpdateView.as_view(), name="chainadmin_admin_editar"),
    path("chainadmin/admins/<int:user_id>/password/", ChainAdminAdminsPasswordView.as_view(), name="chainadmin_admin_password"),
    path("chainadmin/admins/<int:user_id>/toggle/", ChainAdminAdminsToggleActiveView.as_view(), name="chainadmin_admin_toggle"),

    # ===== ChainAdmin — Sucursales (CRUD) =====
    path("chainadmin/sucursales/", ChainAdminSucursalListView.as_view(), name="chainadmin_sucursales"),
    path("chainadmin/sucursales/nueva/", ChainAdminSucursalCreateView.as_view(), name="chainadmin_sucursal_nueva"),
    path("chainadmin/sucursales/<int:pk>/editar/", ChainAdminSucursalUpdateView.as_view(), name="chainadmin_sucursal_editar"),
    path("chainadmin/sucursales/<int:pk>/eliminar/", ChainAdminSucursalDeleteView.as_view(), name="chainadmin_sucursal_eliminar"),

    # ===== APIs del store locator =====
    path("api/sucursales.json", api_sucursales, name="api_sucursales"),
    path("api/sucursales/nearby/", api_sucursales_nearby, name="api_sucursales_nearby"),
    
    
    
    # Store locator (mapa público)
    path("sucursales/", store_locator, name="store_locator"),
    path("sucursales/grid/", views.sucursales_grid, name="sucursales_grid"),
    path("staff/buscar-folio/", views.admin_buscar_folio, name="admin_buscar_folio"),


# APIs del store locator
    path("seleccionar_sucursal/", seleccionar_sucursal, name="seleccionar_sucursal"),
    path("api/sucursales/nearby", api_sucursales_nearby, name="api_sucursales_nearby"),
    path("sucursales/", store_locator, name="store_locator"),  # opcional
    
    
   
    path("admin/global/", ChainGlobalDashboardView.as_view(), name="chain_global_dashboard"),
    path("admin/global/roles/create/", ChainGlobalRoleCreateView.as_view(), name="chain_global_role_create"),
    path("admin/global/roles/<int:pk>/toggle/", ChainGlobalRoleToggleActiveView.as_view(), name="chain_global_role_toggle"),
    path("admin/global/roles/create-user/", CreateCountryAdminUserView.as_view(), name="chain_global_create_country_admin_user"),  # NUEVO
    
    path("api/sucursales.json", SucursalesJsonView.as_view(), name="api_sucursales"),
    path("api/reservas/create_from_local/", ReservaCreateFromLocalView.as_view(), name="api_reservas_create_from_local"),
    
]


