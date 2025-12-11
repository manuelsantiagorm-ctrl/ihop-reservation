# reservas/urls.py
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required

from . import views
from .views import seleccionar_sucursal

# Store locator / APIs públicas
from .views_storelocator import (
    store_locator,
    api_sucursales,
    api_sucursales_nearby,
)
from .views_chainadmin_menu import (
    MenuCatalogListView,
    CategoryCreateView, CategoryUpdateView,
    MenuItemCreateView, MenuItemUpdateView,
    combo_edit_components, combo_delete_component,
    menuitem_toggle_active, api_buscar_items,
)
from . import views_orders

# POS (órdenes en modal del mapa) — usa SIEMPRE este alias
from . import views_ordenes as ordenes

# Catálogo (ChainAdmin)
from .views_chainadmin_menu import (
    MenuCatalogListView,
    CategoryCreateView, CategoryUpdateView,
    MenuItemCreateView, MenuItemUpdateView,
    combo_edit_components, combo_delete_component,
    menuitem_toggle_active, api_buscar_items,
)
from .views_chainadmin_menu import MenuCatalogListView
from . import views_ordenes

# Staff: crear orden rápida (legacy opcional)
from .views_staff_orders import crear_orden_mesa

# Legacy Orders / KDS / Ticket (mantener)
from .views_orders import (
    mesa_panel_order, add_item, submit_to_kitchen, cobrar_cerrar,
    kds_list, ticket_order, kds_data,
)

# ⚠️ IMPORTA AQUÍ EL NUEVO kds_update_status DEL STAFF
from .views_staff_orders import kds_update_status


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

from .views_mesas_api import api_mesas_sucursal  # API mesas para mapa

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
    AnalyticsCompareView,
)

# APIs varias
from .views_api import SucursalesJsonView, ReservaCreateFromLocalView

# Country selector (cookie/sesión)
from .views_country import set_country

# Staff: listado sucursales
from .views_staff import StaffSucursalesListView
from .views_country_dashboard import CountryAdminDashboardView

# Mapa staff protegido + APIs AJAX del mapa
from .views_admin_mapa import AdminMapaSucursalView
from .views_mapa_api import api_list_mesas, api_guardar_posiciones


app_name = "reservas"

urlpatterns = [
    # ===== Público / cliente =====
    path("", views.home, name="home"),
    path("register/", views.register, name="register"),
    path("perfil/", views.perfil, name="perfil"),
    path("mis_reservas/", views.mis_reservas, name="mis_reservas"),
    path("seleccionar_sucursal/", seleccionar_sucursal, name="seleccionar_sucursal"),
    path("reservar/<int:mesa_id>/", views.reservar, name="reservar"),

    # Disponibilidad (cliente)
    path("mesas/<int:mesa_id>/disponibilidad.json", views.disponibilidad_mesa, name="disponibilidad_mesa_json"),
    path("disponibilidad/mesa/<int:mesa_id>/", views.disponibilidad_mesa, name="disponibilidad_mesa"),

    # Flujo de reserva cliente
    path("reserva/exito/<int:reserva_id>/", views.reserva_exito, name="reserva_exito"),
    path("reserva/<int:reserva_id>/confirmar/", views.confirmar_reserva, name="confirmar_reserva"),

    # ===== Store locator (mapa público) =====
    path("sucursales/", store_locator, name="store_locator"),
    path("sucursales/grid/", views.sucursales_grid, name="sucursales_grid"),

    # ===== Staff (prefijo /staff/) =====
    path("staff/sucursales/", views.admin_sucursales, name="admin_sucursales"),
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

    # API de mesas (mapa)
    path("staff/api/mesa/<int:mesa_id>/update/", views.admin_api_mesa_update, name="admin_api_mesa_update"),
    path("staff/api/mesa/<int:mesa_id>/pos/", views.admin_api_mesa_pos, name="admin_api_mesa_pos"),
    path("staff/api/mesa/create/", views.admin_api_mesa_create, name="admin_api_mesa_create"),
    path("staff/mesas/<int:mesa_id>/setpos/", views.admin_api_mesa_setpos, name="admin_api_mesa_setpos"),
    path("staff/api/sucursales/<int:sucursal_id>/mesas/", api_list_mesas, name="api_list_mesas"),
    path("staff/api/sucursales/<int:sucursal_id>/posiciones/guardar/", api_guardar_posiciones, name="api_guardar_posiciones"),
    path("staff/sucursal/<int:sucursal_id>/api/recepcion/pos/", views.admin_api_recepcion_pos, name="admin_api_recepcion_pos"),

    # Bloqueos
    path("staff/api/bloqueo/create/", views.admin_api_bloqueo_create, name="admin_api_bloqueo_create"),
    path("staff/api/bloqueo/list/", views.admin_api_bloqueo_list, name="admin_api_bloqueo_list"),
    path("staff/api/bloqueo/delete/", staff_member_required(views.admin_api_bloqueo_delete), name="admin_api_bloqueo_delete"),

    # Disponibilidad staff
    path("staff/disponibilidad/mesa/<int:mesa_id>/", views.admin_disponibilidad_mesa, name="admin_disponibilidad_mesa"),
    path("staff/agenda/mesa/<int:mesa_id>/", views.agenda_mesa, name="agenda_mesa"),
    path("staff/api/disponibilidad/", views.staff_api_disponibilidad, name="staff_api_disponibilidad"),
    path("staff/api/disponibilidad/json/", views.staff_disponibilidad_json, name="staff_disponibilidad_json"),

    # Reservas staff
    path("staff/reservas/", views.admin_reservas, name="admin_reservas"),
    path("staff/reservas/<int:reserva_id>/finalizar/", views.admin_finalizar_reserva, name="admin_finalizar_reserva"),
    path("staff/reservas/<int:reserva_id>/reasignar/", views.admin_reasignar_reserva, name="admin_reasignar_reserva"),
    path("staff/reserva/<int:reserva_id>/confirmar-llegada/", views.admin_confirmar_llegada, name="admin_confirmar_llegada"),

    # Mesas disponibles
    path("staff/sucursal/<int:sucursal_id>/mesas/", views.ver_mesas, name="admin_mesas_disponibles"),

    # Detalle sucursal pública
    path("s/<slug:slug>/", views.sucursal_detalle, name="sucursal_detalle"),

    # Flujo reserva cliente (slots/auto)
    path("sucursal/<int:sucursal_id>/reservar-slot/", views.reservar_slot, name="reservar_slot"),
    path("sucursal/<int:sucursal_id>/reservar-auto/", views.reservar_auto, name="reservar_auto"),

    # APIs públicas varias
    path("api/sucursales.json", SucursalesJsonView.as_view(), name="api_sucursales"),
    path("api/sucursales/nearby/", api_sucursales_nearby, name="api_sucursales_nearby"),
    path("api/sucursal/<int:sucursal_id>/slots/", views.api_slots_sucursal, name="api_slots_sucursal"),
    path("api/reservas/create_from_local/", ReservaCreateFromLocalView.as_view(), name="api_reservas_create_from_local"),

    # Selector de país
    path("set-country/", set_country, name="set_country"),

    # Health checks
    path("healthz/", views.healthz, name="healthz"),
    path("readyz/", views.readyz, name="readyz"),

    # ===== ChainAdmin — Administradores =====
    path("chainadmin/admins/", ChainAdminAdminsListView.as_view(), name="chainadmin_admins"),
    path("chainadmin/admins/nuevo/", ChainAdminAdminsCreateView.as_view(), name="chainadmin_admin_nuevo"),
    path("chainadmin/admins/<int:user_id>/editar/", ChainAdminAdminsUpdateView.as_view(), name="chainadmin_admin_editar"),
    path("chainadmin/admins/<int:user_id>/password/", ChainAdminAdminsPasswordView.as_view(), name="chainadmin_admin_password"),
    path("chainadmin/admins/<int:user_id>/toggle/", ChainAdminAdminsToggleActiveView.as_view(), name="chainadmin_admin_toggle"),
    path("chainadmin/admins/all/", ChainAdminAdminsAllView.as_view(), name="chainadmin_admins_all"),
    path("chainadmin/admins/<int:user_id>/", ChainAdminAdminDetailView.as_view(), name="chainadmin_admin_detail"),

    # ===== ChainAdmin — Sucursales =====
    path("chainadmin/sucursales/", ChainAdminSucursalListView.as_view(), name="chainadmin_sucursales"),
    path("chainadmin/sucursales/nueva/", ChainAdminSucursalCreateView.as_view(), name="chainadmin_sucursal_nueva"),
    path("chainadmin/sucursales/<int:pk>/editar/", ChainAdminSucursalUpdateView.as_view(), name="chainadmin_sucursal_editar"),
    path("chainadmin/sucursales/<int:pk>/eliminar/", ChainAdminSucursalDeleteView.as_view(), name="chainadmin_sucursal_eliminar"),

    # ===== Chain Global / Roles por país =====
    path("admin/global/", ChainGlobalDashboardView.as_view(), name="chain_global_dashboard"),
    path("admin/global/roles/create/", ChainGlobalRoleCreateView.as_view(), name="chain_global_role_create"),
    path("admin/global/roles/<int:pk>/toggle/", ChainGlobalRoleToggleActiveView.as_view(), name="chain_global_role_toggle"),
    path("admin/global/roles/create-user/", CreateCountryAdminUserView.as_view(), name="chain_global_create_country_admin_user"),

    # ===== Analytics =====
    path("chainadmin/analytics/", AnalyticsPageView.as_view(), name="chainadmin_analytics"),
    path("chainadmin/analytics/data/", AnalyticsDataView.as_view(), name="chainadmin_analytics_data"),
    path("chainadmin/analytics/sucursales/", BranchesForCountryView.as_view(), name="analytics-branches"),
    path("chainadmin/analytics/compare/", AnalyticsCompareView.as_view(), name="analytics-compare"),

    # ===== Dashboard Staff =====
    path("admin/dashboard/", views.admin_dashboard, name="admin_dashboard"),
    path("admin/acciones/cancelar/", views.admin_cancelar_por_folio, name="admin_cancelar_por_folio"),
    path("admin/acciones/checkin/",  views.admin_checkin_por_folio,  name="admin_checkin_por_folio"),
    path("admin/acciones/reactivar/", views.admin_reactivar_por_folio, name="admin_reactivar_por_folio"),
    path("staff/walkin/", views.admin_walkin_reserva, name="admin_walkin_reserva"),
    path("reserva/<int:pk>/", views.reserva_detalle, name="reserva_detalle"),
    path("r/<str:folio>/", views.reserva_scan_entry, name="reserva_scan_entry"),
    path("r/<str:folio>/checkin/", views.reserva_checkin, name="reserva_checkin"),
    path("chainadmin/dashboard/", CountryAdminDashboardView.as_view(), name="chainadmin_dashboard_country"),

    # ===== Legacy Orders / KDS / Ticket =====
    path("admin/mesas/<int:mesa_id>/orden/", mesa_panel_order, name="mesa_panel_order"),
    path("admin/orders/<int:order_id>/add-item/", add_item, name="order_add_item"),
    path("admin/orders/<int:order_id>/submit/", submit_to_kitchen, name="order_submit"),
    path("admin/orders/<int:order_id>/cobrar/", cobrar_cerrar, name="order_cobrar"),
    path("admin/kds/", kds_list, name="kds"),
    path("admin/kds/<int:order_id>/status/", kds_update_status, name="kds_update_status"),
    path("admin/orders/<int:order_id>/ticket/", ticket_order, name="ticket_order"),

    # ===== POS nuevo – modal del mapa =====
    path("orden/nueva/", ordenes.orden_mesa_nueva, name="orden_mesa_nueva"),

    # Buscador del modal
    path("api/menu/buscar/", ordenes.api_menu_buscar, name="menu_api_buscar"),

    # CRUD de renglones de la orden (POS)
    path("api/orden/crear/", ordenes.api_orden_crear, name="api_orden_crear"),
    path("api/orden/<int:orden_id>/", ordenes.api_orden_detalle, name="api_orden_detalle"),
    path("api/orden/item/update/", ordenes.api_orden_item_update, name="api_orden_item_update"),
    path("api/orden/item/split/",  ordenes.api_orden_item_split,  name="api_orden_item_split"),
    path("api/orden/item/remove/", ordenes.api_orden_item_remove, name="api_orden_item_remove"),

    # Enviar orden POS a cocina (nuevo endpoint que sincroniza con KDS)
    path(
        "api/orden-pos/<int:orden_id>/enviar/",
        ordenes.api_orden_pos_enviar_cocina,
        name="api_orden_pos_enviar_cocina",
    ),

    # alias opcional por compatibilidad con tu JS viejo
    path("api/orden/item/quitar/", ordenes.api_orden_item_remove, name="api_orden_quitar_item"),

    # (Opcional) crear orden rápida legacy
    path("staff/ordenes/nueva/", staff_member_required(crear_orden_mesa), name="orden_mesa_nueva_rapida"),
    
    path("staff/buscar-folio/", views.admin_buscar_folio, name="admin_buscar_folio"),

    # --- Catálogo (ChainAdmin) ---
    path("chainadmin/menu/", MenuCatalogListView.as_view(), name="chainadmin_menu_catalogo"),

    # Categorías
    path("chainadmin/menu/categoria/nueva/", CategoryCreateView.as_view(),
         name="chainadmin_menu_categoria_nueva"),
    path("chainadmin/menu/categoria/<int:pk>/editar/", CategoryUpdateView.as_view(),
         name="chainadmin_menu_categoria_editar"),

    # Ítems
    path("chainadmin/menu/item/nuevo/", MenuItemCreateView.as_view(),
         name="chainadmin_menu_item_nuevo"),
    path("chainadmin/menu/item/<int:pk>/editar/", MenuItemUpdateView.as_view(),
         name="chainadmin_menu_item_editar"),
    path("chainadmin/menu/item/<int:pk>/toggle/", menuitem_toggle_active,
         name="chainadmin_menu_item_toggle"),

    # Combos
    path("chainadmin/menu/combo/<int:pk>/", combo_edit_components,
         name="chainadmin_menu_combo"),
    path("chainadmin/menu/combo/<int:pk>/comp/<int:comp_id>/del/", combo_delete_component,
         name="chainadmin_menu_combo_comp_del"),

    # API de búsqueda (para formularios del catálogo)
    path("chainadmin/menu/api/buscar-items/", api_buscar_items,
         name="chainadmin_menu_api_buscar_items"),
    
    # JSON para el KDS
    path("admin/kds/data/", kds_data, name="kds_data"),
    
     # Cobrar y cerrar desde POS (puente a Order/ticket)
    path(
        "api/orden-pos/<int:orden_id>/cobrar/",
        ordenes.api_orden_pos_cobrar,
        name="api_orden_pos_cobrar",
    ),

    path(
        "api/orden-pos/<int:order_id>/item/update/",
        views_orders.api_orden_pos_item_update,
        name="api_orden_pos_item_update",
    ),
    path(
    "staff/ordenes/<int:order_id>/item-update/",
    views_orders.api_orden_pos_item_update,
    name="api_orden_pos_item_update",
    ),

]

    
