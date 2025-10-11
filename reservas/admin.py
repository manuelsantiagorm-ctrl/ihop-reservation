# reservas/admin.py
from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Pais,
    ChainOwnerPaisRole,
    Sucursal,
    SucursalFoto,
    Mesa,
    Cliente,
    Reserva,
    PerfilAdmin,
    BloqueoMesa,
    MenuCategoria,
    MenuItem,
    Review,
)

# Si tienes el helper de correo, mantenlo opcional para no romper si no existe.
try:
    from .emails import enviar_correo_reserva_confirmada
except Exception:  # pragma: no cover
    def enviar_correo_reserva_confirmada(*args, **kwargs):
        return None


# ==============================================================================
# Helpers de alcance (visibilidad por usuario)
# ==============================================================================
def is_chain_owner(user) -> bool:
    """Dueño de cadena: superuser o con permiso manage_branches."""
    return getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches")


def _sucursales_visibles_qs(user):
    """
    - Dueño de cadena -> todas
    - Staff con PerfilAdmin asignado -> esa sucursal
    - Staff administrador (M2M) -> sus sucursales
    - Otros -> ninguna
    """
    if not getattr(user, "is_authenticated", False):
        return Sucursal.objects.none()
    if is_chain_owner(user):
        return Sucursal.objects.all()

    # PerfilAdmin (sucursal asignada)
    try:
        perfil = PerfilAdmin.objects.get(user=user)
    except PerfilAdmin.DoesNotExist:
        perfil = None
    if perfil and perfil.sucursal_asignada_id:
        return Sucursal.objects.filter(pk=perfil.sucursal_asignada_id)

    # M2M administradores
    return Sucursal.objects.filter(administradores=user).distinct()


# ==============================================================================
# Inlines
# ==============================================================================
class SucursalFotoInline(admin.TabularInline):
    model = SucursalFoto
    extra = 1
    fields = ("imagen", "preview", "alt", "orden")
    readonly_fields = ("preview",)

    def preview(self, obj):
        if obj and getattr(obj, "imagen", None):
            try:
                return format_html(
                    '<img src="{}" style="width:96px; height:64px; object-fit:cover; border-radius:4px;" />',
                    obj.imagen.url,
                )
            except Exception:
                pass
        return "—"

    preview.short_description = "Miniatura"


# ==============================================================================
# Sucursal
# ==============================================================================
@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = (
        "thumb_portada",
        "nombre",
        "pais",          # <- NUEVO en lista
        "timezone",      # <- NUEVO en lista
        "slug",
        "codigo_postal",
        "cocina",
        "precio_nivel",
        "rating",
        "recomendado",
        "activo",
    )
    list_editable = ("recomendado", "activo")
    search_fields = ("nombre", "slug", "direccion", "codigo_postal", "cocina", "place_id")
    list_filter = ("pais", "activo", "recomendado", "precio_nivel")  # <- incluye país
    readonly_fields = ("preview_portada", "slug")  # slug lo genera la señal
    filter_horizontal = ("administradores",)
    inlines = [SucursalFotoInline]

    fieldsets = (
        (
            "Información básica",
            {
                "fields": (
                    "nombre",
                    "slug",  # solo lectura
                    "direccion",
                    "codigo_postal",
                    "pais",        # <- NUEVO en form
                    "timezone",    # <- NUEVO en form
                    "administradores",
                    "activo",
                )
            },
        ),
        (
            "Ubicación (Mapa / Store Locator)",
            {
                "classes": ("collapse",),
                "fields": (
                    "lat",
                    "lng",
                    "place_id",
                    "recepcion_x",
                    "recepcion_y",
                ),
            },
        ),
        (
            "Apariencia en la web",
            {
                "fields": (
                    "portada",
                    "preview_portada",
                    "portada_alt",
                    "cocina",
                    "precio_nivel",
                    "rating",
                    "reviews",
                    "recomendado",
                )
            },
        ),
    )

    # Visibilidad
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_chain_owner(request.user):
            return qs
        return qs.filter(pk__in=_sucursales_visibles_qs(request.user).values("pk"))

    # Permisos de edición
    def get_readonly_fields(self, request, obj=None):
        ro = set(super().get_readonly_fields(request, obj)) | {"slug"}
        if not is_chain_owner(request.user):
            # Staff normal no puede tocar admins ni el nombre
            ro.update({"administradores", "nombre"})
        return list(ro)

    # Vistas previas
    def preview_portada(self, obj):
        if obj.portada:
            return format_html(
                '<img src="{}" style="max-width:420px; height:auto; border-radius:8px;" />',
                obj.portada.url,
            )
        return "(sin portada)"

    preview_portada.short_description = "Vista previa"

    def thumb_portada(self, obj):
        if obj.portada:
            return format_html(
                '<img src="{}" style="width:64px; height:36px; object-fit:cover; border-radius:4px;" />',
                obj.portada.url,
            )
        return "—"

    thumb_portada.short_description = "Portada"


@admin.register(SucursalFoto)
class SucursalFotoAdmin(admin.ModelAdmin):
    list_display = ("mini", "sucursal", "orden", "alt")
    list_editable = ("orden",)
    search_fields = ("sucursal__nombre", "alt")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_chain_owner(request.user):
            return qs
        return qs.filter(sucursal__in=_sucursales_visibles_qs(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal" and not is_chain_owner(request.user):
            kwargs["queryset"] = _sucursales_visibles_qs(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def mini(self, obj):
        if obj.imagen:
            return format_html(
                '<img src="{}" style="width:96px; height:64px; object-fit:cover; border-radius:4px;" />',
                obj.imagen.url,
            )
        return "—"

    mini.short_description = "Miniatura"


# ==============================================================================
# Mesas
# ==============================================================================
@admin.register(Mesa)
class MesaAdmin(admin.ModelAdmin):
    list_display = ("numero", "capacidad", "estado", "sucursal")
    list_filter = ("estado", "sucursal")
    search_fields = ("numero", "sucursal__nombre")
    ordering = ("sucursal", "numero")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_chain_owner(request.user):
            return qs
        return qs.filter(sucursal__in=_sucursales_visibles_qs(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "sucursal" and not is_chain_owner(request.user):
            kwargs["queryset"] = _sucursales_visibles_qs(request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ==============================================================================
# Clientes
# ==============================================================================
@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "email", "telefono", "codigo_postal")
    search_fields = ("nombre", "email", "telefono", "codigo_postal")


# ==============================================================================
# PerfilAdmin (solo dueño de cadena administra asignaciones)
# ==============================================================================
@admin.register(PerfilAdmin)
class PerfilAdminAdmin(admin.ModelAdmin):
    list_display = ("user", "sucursal_asignada")
    list_filter = ("sucursal_asignada",)
    search_fields = ("user__username", "user__email", "sucursal_asignada__nombre")

    def _allow(self, request):
        return is_chain_owner(request.user)

    def has_module_permission(self, request):
        return self._allow(request)

    def has_view_permission(self, request, obj=None):
        return self._allow(request)

    def has_add_permission(self, request):
        return self._allow(request)

    def has_change_permission(self, request, obj=None):
        return self._allow(request)

    def has_delete_permission(self, request, obj=None):
        return self._allow(request)


# ==============================================================================
# Bloqueos
# ==============================================================================
@admin.register(BloqueoMesa)
class BloqueoMesaAdmin(admin.ModelAdmin):
    list_display = ("sucursal", "mesa", "inicio", "fin", "motivo", "creado")
    list_filter = ("sucursal", "mesa")
    search_fields = ("motivo",)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_chain_owner(request.user):
            return qs
        return qs.filter(sucursal__in=_sucursales_visibles_qs(request.user))

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not is_chain_owner(request.user):
            if db_field.name == "sucursal":
                kwargs["queryset"] = _sucursales_visibles_qs(request.user)
            if db_field.name == "mesa":
                kwargs["queryset"] = Mesa.objects.filter(
                    sucursal__in=_sucursales_visibles_qs(request.user)
                )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


# ==============================================================================
# Reservas
# ==============================================================================
@admin.register(Reserva)
class ReservaAdmin(admin.ModelAdmin):
    # Columnas y filtros
    list_display = (
        "folio",
        "estado",
        "fecha",            # legacy (hora local)
        "mesa",
        "sucursal_nombre",  # derivado via mesa
        "cliente_nombre",
        "cliente_email",
        "num_personas",
    )
    list_filter = ("estado", "mesa__sucursal", "fecha")
    search_fields = (
        "folio",
        "cliente__nombre",
        "cliente__email",
        "mesa__sucursal__nombre",
    )
    date_hierarchy = "fecha"
    ordering = ("-fecha",)

    # Acciones
    actions = ["cancelar_reservas", "marcar_confirmada_y_enviar_correo"]

    # Restringir queryset por sucursal asignada
    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("mesa__sucursal", "cliente")
        if request.user.is_superuser:
            return qs
        return qs.filter(mesa__sucursal__in=_sucursales_visibles_qs(request.user))

    # Limitar choices en FKs relevantes
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser and db_field.name == "mesa":
            kwargs["queryset"] = Mesa.objects.filter(
                sucursal__in=_sucursales_visibles_qs(request.user)
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    # Columnas calculadas
    @admin.display(description="Sucursal")
    def sucursal_nombre(self, obj):
        return obj.mesa.sucursal.nombre

    @admin.display(description="Cliente")
    def cliente_nombre(self, obj):
        return getattr(obj.cliente, "nombre", "")

    @admin.display(description="Email")
    def cliente_email(self, obj):
        return getattr(obj.cliente, "email", "")

    # Acciones
    @admin.action(description="Cancelar reservas seleccionadas")
    def cancelar_reservas(self, request, queryset):
        updated = queryset.update(estado="CANC")
        self.message_user(request, f"{updated} reservas fueron canceladas.")

    @admin.action(description="Marcar como CONFIRMADA y enviar correo")
    def marcar_confirmada_y_enviar_correo(self, request, queryset):
        count = 0
        for reserva in queryset:
            if reserva.estado != "CONF":
                reserva.estado = "CONF"
                reserva.save(update_fields=["estado"])
                try:
                    enviar_correo_reserva_confirmada(reserva, bcc_sucursal=True)
                except Exception as e:
                    self.message_user(
                        request,
                        f"Fallo al enviar correo para {reserva.folio}: {e}",
                        level="warning",
                    )
                else:
                    count += 1
        self.message_user(request, f"{count} reservas confirmadas y correo enviado.")


# ==============================================================================
# Menú y Reseñas (mismo criterio de visibilidad)
# ==============================================================================
class _SucursalScopeMixin(admin.ModelAdmin):
    """Restringe queryset a sucursales visibles para el usuario (salvo dueño de cadena)."""

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if is_chain_owner(request.user):
            return qs
        visibles = _sucursales_visibles_qs(request.user)
        # Por modelo:
        if hasattr(self.model, "sucursal"):
            return qs.filter(sucursal__in=visibles)
        if self.model is MenuItem:
            return qs.filter(categoria__sucursal__in=visibles)
        return qs.none()


@admin.register(MenuCategoria)
class MenuCategoriaAdmin(_SucursalScopeMixin):
    list_display = ("titulo", "sucursal", "orden")
    list_filter = ("sucursal",)
    search_fields = ("titulo", "sucursal__nombre")
    ordering = ("sucursal", "orden")


@admin.register(MenuItem)
class MenuItemAdmin(_SucursalScopeMixin):
    list_display = ("nombre", "categoria", "precio", "activo", "orden")
    list_filter = ("categoria__sucursal", "categoria", "activo")
    search_fields = ("nombre", "categoria__titulo")
    ordering = ("categoria__sucursal", "categoria__orden", "orden")


@admin.register(Review)
class ReviewAdmin(_SucursalScopeMixin):
    list_display = ("sucursal", "autor", "rating", "creado")
    list_filter = ("sucursal", "rating")
    search_fields = ("autor", "texto", "sucursal__nombre")
    ordering = ("-creado",)


# ==============================================================================
# Países y ChainOwners por país
# ==============================================================================
@admin.register(Pais)
class PaisAdmin(admin.ModelAdmin):
    list_display = ("nombre", "iso2")
    search_fields = ("nombre", "iso2")
    ordering = ("nombre",)


@admin.register(ChainOwnerPaisRole)
class ChainOwnerPaisRoleAdmin(admin.ModelAdmin):
    list_display = ("user", "pais", "activo", "creado_en")
    list_filter = ("activo", "pais")
    search_fields = ("user__email", "user__username", "pais__iso2")
    autocomplete_fields = ("user", "pais")
