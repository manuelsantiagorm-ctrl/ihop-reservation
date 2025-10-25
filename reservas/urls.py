# reservas/urls.py
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required

from . import views

# Store locator / APIs públicas
from .views_storelocator import (
    store_locator,
    api_sucursales,
    api_sucursales_nearby,
    seleccionar_sucursal,
)

# ChainAdmin: Admins de sucursal
from .views_chainadmin_admins import (
    ChainAdminAdminsListView,
    ChainAdminAdminsCreateView,
    ChainAdminAdminsUpdateView,
    ChainAdminAdminsPasswordView,
    ChainAdminAdminsToggleActiveView,
    ChainAdminAdminsAllView,
    ChainAdminAdminDetailView,
    CountryAdminsAllView,
    CountryAdminDetailView,
)

# ChainAdmin: Sucursales (CRUD)
from .views_chainadmin import (
    ChainAdminSucursalListView,
    ChainAdminSucursalCreateView,
    ChainAdminSucursalUpdateView,
    ChainAdminSucursalDeleteView,
)

# Chain Global (roles por país)
from .views_chain_global import (
    ChainGlobalDashboardView,
    ChainGlobalRoleCreateView,
    ChainGlobalRoleToggleActiveView,
    CreateCountryAdminUserView,
)

# Analytics
from .views_analytics import (
    AnalyticsPageView,
    AnalyticsDataView,
    BranchesForCountryView,
    AnalyticsCompareView,)

# APIs varias
from .views_api import SucursalesJsonView, ReservaCreateFromLocalView

# Country selector (cookie/sesión)
from .views_country import set_country

# Staff: listado sucursales filtrado (CBV tipo tabla)
from .views_staff import StaffSucursalesListView

# Mapa staff protegido + APIs AJAX del mapa
from .views_admin_mapa import AdminMapaSucursalView
from .views_mapa_api import api_list_mesas, api_guardar_posiciones

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

    # ===== Store locator (mapa público) =====
    path("sucursales/", store_locator, name="store_locator"),
    # grid opcional
    path("sucursales/grid/", views.sucursales_grid, name="sucursales_grid"),

    # ===== Staff (prefijo /staff/) =====
    # Vista CLÁSICA (tarjetas) — la que quieres al entrar en /staff/sucursales/
    path("staff/sucursales/", views.admin_sucursales, name="admin_sucursales"),

    # Vista NUEVA (tabla/CBV) — la conservamos en otra URL para no chocar
    path("staff/sucursales/lista/", StaffSucursalesListView.as_view(), name="staff_sucursales"),

    path("staff/sucursales/nueva/", views.admin_sucursal_form, name="admin_sucursal_nueva"),
    path("staff/sucursales/<int:pk>/editar/", views.admin_sucursal_form, name="admin_sucursal_editar"),
    path("staff/sucursales/<int:sucursal_id>/contenido/", views.admin_sucursal_contenido, name="admin_sucursal_contenido"),
    path("staff/sucursal/<int:sucursal_id>/bloqueos/", views.admin_bloqueos, name="admin_bloqueos"),

    # Mapa y mesas (vista protegida)
    path("staff/sucursal/<int:sucursal_id>/mapa/", AdminMapaSucursalView.as_view(), name="admin_mapa_sucursal"),
    path("staff/mesa/<int:mesa_id>/", views.admin_mesa_detalle, name="admin_mesa_detalle"),
    path("staff/mesa/<int:mesa_id>/editar/", views.admin_mesa_editar, name="admin_editar_mesa"),
    path("staff/sucursal/<int:sucursal_id>/mesa/crear/", views.admin_mesa_crear, name="admin_mesa_crear"),

    # API de mesas (legacy específicas por mesa — se mantienen)
    path("staff/api/mesa/<int:mesa_id>/update/", views.admin_api_mesa_update, name="admin_api_mesa_update"),
    path("staff/api/mesa/<int:mesa_id>/pos/", views.admin_api_mesa_pos, name="admin_api_mesa_pos"),
    path("staff/api/mesa/create/", views.admin_api_mesa_create, name="admin_api_mesa_create"),
    path("staff/mesas/<int:mesa_id>/setpos/", views.admin_api_mesa_setpos, name="admin_api_mesa_setpos"),

    # APIs AJAX del mapa (protegidas por país/sucursal)
    path("staff/api/sucursales/<int:sucursal_id>/mesas/", api_list_mesas, name="api_list_mesas"),
    path("staff/api/sucursales/<int:sucursal_id>/posiciones/guardar/", api_guardar_posiciones, name="api_guardar_posiciones"),

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
    path("api/sucursales.json", SucursalesJsonView.as_view(), name="api_sucursales"),
    path("api/sucursales/nearby/", api_sucursales_nearby, name="api_sucursales_nearby"),

    # Búsqueda staff por folio
    path("staff/buscar-folio/", views.admin_buscar_folio, name="admin_buscar_folio"),

    # ===== Chain Global / Roles por país =====
    path("admin/global/", ChainGlobalDashboardView.as_view(), name="chain_global_dashboard"),
    path("admin/global/roles/create/", ChainGlobalRoleCreateView.as_view(), name="chain_global_role_create"),
    path("admin/global/roles/<int:pk>/toggle/", ChainGlobalRoleToggleActiveView.as_view(), name="chain_global_role_toggle"),
    path("admin/global/roles/create-user/", CreateCountryAdminUserView.as_view(), name="chain_global_create_country_admin_user"),

    # ===== APIs varias =====
    path("api/reservas/create_from_local/", ReservaCreateFromLocalView.as_view(), name="api_reservas_create_from_local"),

    # Selector de país (UI)
    path("set-country/", set_country, name="set_country"),

    # Vistas auxiliares de referents/country-admins
    path("chainadmin/admins/all/", ChainAdminAdminsAllView.as_view(), name="chainadmin_admins_all"),
    path("chainadmin/admins/<int:user_id>/", ChainAdminAdminDetailView.as_view(), name="chainadmin_admin_detail"),
    path("chainadmin/referentes/", CountryAdminsAllView.as_view(), name="chainadmin_country_admins_all"),
    path("chainadmin/referentes/<int:user_id>/", CountryAdminDetailView.as_view(), name="chainadmin_country_admin_detail"),

    # Analytics
    path("chainadmin/analytics/", AnalyticsPageView.as_view(), name="chainadmin_analytics"),
    path("chainadmin/analytics/data/", AnalyticsDataView.as_view(), name="chainadmin_analytics_data"),
    path("chainadmin/analytics/sucursales/", BranchesForCountryView.as_view(), name="analytics-branches"),
    path("chainadmin/analytics/sucursales/", BranchesForCountryView.as_view(), name="analytics-branches"),
    path("chainadmin/analytics/compare/", AnalyticsCompareView.as_view(), name="analytics-compare"),

    # ▼ Dashboard Staff (usa tus vistas existentes en views.py)
    path("admin/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/acciones/cancelar/", views.admin_cancelar_por_folio, name="admin_cancelar_por_folio"),
    path("admin/acciones/checkin/",  views.admin_checkin_por_folio,  name="admin_checkin_por_folio"),
    path("admin/acciones/reactivar/", views.admin_reactivar_por_folio, name="admin_reactivar_por_folio"),
    
    path("staff/walkin/", views.admin_walkin_reserva, name="admin_walkin_reserva"),

]
