# reservas/models.py
from __future__ import annotations
import secrets
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo  # <- NUEVO
from django.db.models import Q
from django.apps import apps
from django.db import models
from django.utils.timezone import is_naive




# Helpers/QuerySet (ajusta los imports si en tu proyecto están en otro módulo)
from .utils import  booking_total_minutes
from .querysets import ReservaQuerySet
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Avg, Count
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify
from django_countries.fields import CountryField

# ==============================================================
# Utilidades generales
# ==============================================================

def generar_folio() -> str:
    """Folio: R-YYYYMMDD-XXXXXX (ej. R-20250916-A3F91C)"""
    tz = timezone.get_current_timezone()
    today_str = timezone.now().astimezone(tz).strftime("%Y%m%d")
    suffix = secrets.token_hex(3).upper()  # 6 chars hex
    return f"R-{today_str}-{suffix}"

# Validator CP México
cp_mx_validator = RegexValidator(
    regex=r"^\d{5}$",
    message="El código postal debe tener 5 dígitos.",
)

# Para relaciones a usuario, usar el string del modelo configurado
User = settings.AUTH_USER_MODEL

# ==============================================================
# MODELOS NUEVOS (Multi-país / Roles por país)
# ==============================================================

class Pais(models.Model):
    iso2 = models.CharField(max_length=2, unique=True)  # MX, US, ES...
    nombre = models.CharField(max_length=80)

    class Meta:
        verbose_name = "País"
        verbose_name_plural = "Países"
        ordering = ["nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.iso2})"


class ChainOwnerPaisRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="roles_pais")
    pais = models.ForeignKey(Pais, on_delete=models.CASCADE, related_name="chainowners")
    activo = models.BooleanField(default=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "pais")
        verbose_name = "Administrador País (ChainOwner)"
        verbose_name_plural = "Administradores País (ChainOwners)"

    def __str__(self):
        estado = "activo" if self.activo else "inactivo"
        return f"{self.user} → {self.pais.iso2} ({estado})"

# ==============================================================
# QuerySets con reglas de visibilidad
# ==============================================================

class SucursalQuerySet(models.QuerySet):
    def for_user(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()

        # Superuser o permiso global => todas
        if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
            return self

        filtros = Q(pk__in=[])
        pais_ids = set()

        # 1) Países por perfiladmin.paises
        perfil = getattr(user, "perfiladmin", None)
        if perfil and hasattr(perfil, "paises"):
            pais_ids.update(perfil.paises.values_list("id", flat=True))

        # 2) Países por CountryAdminScope (sin import circular y tolerante a activo/is_active)
        scope_model = apps.get_model("reservas", "CountryAdminScope")
        if scope_model is not None:
            scope_qs = scope_model.objects.filter(user=user)
            scope_fields = {f.name for f in scope_model._meta.get_fields()}
            if "activo" in scope_fields:
                scope_qs = scope_qs.filter(activo=True)
            elif "is_active" in scope_fields:
                scope_qs = scope_qs.filter(is_active=True)
            # si no hay campo de activo, no filtramos por estado
            pais_ids.update(scope_qs.values_list("pais_id", flat=True))

        if pais_ids:
            filtros |= Q(pais_id__in=pais_ids)

        # 3) Sucursal asignada directamente
        suc_id = getattr(perfil, "sucursal_asignada_id", None) if perfil else None
        if suc_id:
            filtros |= Q(pk=suc_id)

        # 4) Administradores M2M
        filtros |= Q(administradores=user)

        return self.filter(filtros).distinct()

    def visibles_para(self, user):
        return self.for_user(user)




class OwnedBySucursalQuerySet(models.QuerySet):
    """Para modelos con FK directo 'sucursal' (Mesa, BloqueoMesa, Menú, Review)."""
    def visible_for(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
            return self
        perfil = getattr(user, "perfiladmin", None)
        if perfil and perfil.sucursal_asignada_id:
            return self.filter(sucursal_id=perfil.sucursal_asignada_id)
        return self.filter(sucursal__administradores=user).distinct()

class ReservaQuerySet(models.QuerySet):
    """Para Reserva (si filtras por mesa__sucursal o por el campo sucursal directo)."""
    def visible_for(self, user):
        if not getattr(user, "is_authenticated", False):
            return self.none()
        if getattr(user, "is_superuser", False) or user.has_perm("reservas.manage_branches"):
            return self
        perfil = getattr(user, "perfiladmin", None)
        if perfil and perfil.sucursal_asignada_id:
            # Si usas el FK directo a sucursal en Reserva:
            return self.filter(sucursal_id=perfil.sucursal_asignada_id)
        return self.filter(mesa__sucursal__administradores=user).distinct()

# ==============================================================
# Helpers de duración (con fallback si no existe utils.booking_total_minutes)
# ==============================================================

try:
    from .utils import booking_total_minutes  # (dt: datetime, party: int) -> int
except Exception:
    def booking_total_minutes(dt: datetime, party: int) -> int:
        RESERVA_DURACION_MIN_NORM = int(getattr(settings, "RESERVA_DURACION_MIN_NORM", 90))
        RESERVA_DURACION_MIN_PICO = int(getattr(settings, "RESERVA_DURACION_MIN_PICO", 105))
        HORAS_PICO = list(getattr(settings, "HORAS_PICO", [(12, 15), (18, 21)]))
        extra = 15 if int(party or 2) >= 5 else 0
        local = timezone.localtime(dt) if timezone.is_aware(dt) else dt
        es_pico = any(i <= local.hour < f for (i, f) in HORAS_PICO)
        base = RESERVA_DURACION_MIN_PICO if es_pico else RESERVA_DURACION_MIN_NORM
        return int(base + extra)

# ==============================================================
# MODELOS
# ==================================
class Sucursal(models.Model):
    objects = SucursalQuerySet.as_manager()   # ← IMPORTANTE
    nombre = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True, blank=True)
    direccion = models.CharField(max_length=255, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)
    portada = models.ImageField(upload_to="sucursales/portadas/", blank=True, null=True)
    portada_alt = models.CharField(max_length=120, blank=True)
    cocina = models.CharField(max_length=80, blank=True)
    # ✅ NUEVO
    email_contacto = models.EmailField(max_length=120, blank=True, null=True)

    # Geo (para mapa y store-locator)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    place_id = models.CharField(max_length=255, null=True, blank=True)

    # Plano de recepción por porcentaje 0..100
    recepcion_x = models.PositiveSmallIntegerField(
        default=3, help_text="Porcentaje X 0..100 para la recepción"
    )
    recepcion_y = models.PositiveSmallIntegerField(
        default=3, help_text="Porcentaje Y 0..100 para la recepción"
    )

    # Ficha pública
    PRECIO_CHOICES = [(1, "$"), (2, "$$"), (3, "$$$")]
    precio_nivel = models.PositiveSmallIntegerField(choices=PRECIO_CHOICES, default=1)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)  # 0–5.00
    reviews = models.PositiveIntegerField(default=0)
    recomendado = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)

    administradores = models.ManyToManyField(
        User,
        blank=True,
        related_name="sucursales_que_administra",
    )

    # Multi-país + Timezone por sucursal
    pais = models.ForeignKey(
        "Pais", null=True, blank=True, on_delete=models.PROTECT, related_name="sucursales"
    )
    timezone = models.CharField(
        max_length=64, null=True, blank=True, help_text="IANA TZ (ej. America/Mexico_City)"
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    objects = SucursalQuerySet.as_manager()

    class Meta:
        ordering = ["nombre"]
        permissions = [
            ("manage_branches", "Puede administrar/visualizar todas las sucursales"),
        ]
        indexes = [
            models.Index(fields=["pais"]),
            models.Index(fields=["timezone"]),
        ]

    def __str__(self):
        return self.nombre

    def tz(self):
        try:
            return ZoneInfo(self.timezone) if self.timezone else ZoneInfo("UTC")
        except Exception:
            return ZoneInfo("UTC")

class SucursalFoto(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="fotos")
    imagen = models.ImageField(upload_to="sucursales/galeria/")
    alt = models.CharField(max_length=120, blank=True)
    orden = models.PositiveIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)

    # quiénes pueden tocar esta foto específicamente (opcional)
    admins = models.ManyToManyField(User, related_name="sucursales_admin", blank=True)

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.sucursal} · {self.alt or self.imagen.name}"


class Mesa(models.Model):
    ESTADOS = [
        ("disponible", "Disponible"),
        ("reservada", "Reservada"),
        ("ocupada", "Ocupada"),
    ]

    # Zonas para diferenciar interior/terraza/exterior
    ZONAS = [
        ("interior", "Interior"),
        ("terraza", "Terraza"),
        ("exterior", "Exterior"),
    ]

    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="mesas")
    numero = models.PositiveIntegerField()
    capacidad = models.PositiveIntegerField(default=4)
    estado = models.CharField(max_length=20, choices=ESTADOS, default="disponible")

    # Posición relativa en el canvas (porcentaje 0..100)
    zona = models.CharField(max_length=20, choices=ZONAS, default="interior", db_index=True)
    pos_x = models.PositiveSmallIntegerField(default=0, help_text="Porcentaje X 0..100")
    pos_y = models.PositiveSmallIntegerField(default=0, help_text="Porcentaje Y 0..100")

    # Opcionales
    ubicacion = models.CharField(max_length=100, blank=True, null=True)
    notas = models.TextField(blank=True, null=True)
    bloqueada = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["sucursal", "numero"], name="uniq_mesa_por_sucursal"),
        ]
        ordering = ["sucursal", "numero"]

    def __str__(self):
        return f"Mesa {self.numero} - {self.sucursal.nombre}"


class Cliente(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True
    )
    nombre = models.CharField(max_length=100)
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    codigo_postal = models.CharField(
        max_length=10, blank=True, null=True, validators=[cp_mx_validator]
    )

    def __str__(self):
        return self.nombre


class PerfilAdmin(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfiladmin"
    )
    sucursal_asignada = models.ForeignKey(
        Sucursal, on_delete=models.CASCADE, null=True, blank=True, related_name="admins_principales"
    )

    def __str__(self):
        return f"Perfil de {self.user}"


class BloqueoMesa(models.Model):
    sucursal = models.ForeignKey("Sucursal", on_delete=models.CASCADE, related_name="bloqueos")
    # Si es null => bloqueo para TODA la sucursal
    mesa = models.ForeignKey(
        "Mesa", on_delete=models.CASCADE, null=True, blank=True, related_name="bloqueos"
    )
    inicio = models.DateTimeField()
    fin = models.DateTimeField()
    motivo = models.CharField(max_length=200, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    objects = OwnedBySucursalQuerySet.as_manager()

    class Meta:
        verbose_name = "Bloqueo de mesa"
        verbose_name_plural = "Bloqueos de mesa"
        ordering = ["-inicio"]
        indexes = [
            models.Index(fields=["sucursal", "inicio"]),
            models.Index(fields=["sucursal", "fin"]),
            models.Index(fields=["inicio", "fin"]),
        ]

    def clean(self):
        if self.fin <= self.inicio:
            raise ValidationError("El fin debe ser mayor que el inicio.")

    def __str__(self):
        scope = f"Mesa {self.mesa.numero}" if self.mesa_id else "Sucursal completa"
        return f"{scope}: {self.inicio:%Y-%m-%d %H:%M} → {self.fin:%H:%M}"


class MenuCategoria(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="menu_categorias")
    titulo = models.CharField(max_length=120)
    orden = models.PositiveIntegerField(default=0)

    objects = OwnedBySucursalQuerySet.as_manager()

    class Meta:
        ordering = ["orden", "id"]

    def __str__(self):
        return f"{self.sucursal.nombre} · {self.titulo}"


class MenuItem(models.Model):
    categoria = models.ForeignKey(MenuCategoria, on_delete=models.CASCADE, related_name="items")
    nombre = models.CharField(max_length=140)
    desc = models.TextField(blank=True, default="")
    precio = models.DecimalField(max_digits=8, decimal_places=2)  # MXN
    activo = models.BooleanField(default=True)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["categoria__orden", "orden", "id"]

    def __str__(self):
        return f"{self.nombre} (${self.precio})"


class Review(models.Model):
    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name="reviews_obj")
    autor = models.CharField(max_length=120)
    rating = models.PositiveSmallIntegerField()  # 1..5
    texto = models.TextField(blank=True, default="")
    creado = models.DateTimeField(auto_now_add=True)

    objects = OwnedBySucursalQuerySet.as_manager()

    class Meta:
        ordering = ["-creado", "id"]

    def __str__(self):
        return f"{self.sucursal.nombre} · {self.autor} ({self.rating}/5)"

# ==============================================================
# Signals y helpers derivados
# ==============================================================

def _recompute_rating(sucursal: "Sucursal"):
    agg = Review.objects.filter(sucursal=sucursal).aggregate(avg=Avg("rating"), cnt=Count("id"))
    sucursal.rating = round((agg["avg"] or 0), 2)
    sucursal.reviews = agg["cnt"] or 0
    sucursal.save(update_fields=["rating", "reviews"])


@receiver(post_save, sender=Review)
def _rev_saved(sender, instance, **kwargs):
    _recompute_rating(instance.sucursal)


@receiver(post_delete, sender=Review)
def _rev_deleted(sender, instance, **kwargs):
    _recompute_rating(instance.sucursal)

# Slug automático para Sucursal
def _unique_slugify(instance, value, slug_field_name: str = "slug", max_length: int = 255):
    """Genera un slug único; si existe, añade -2, -3, ..."""
    base = slugify(value)[:max_length].strip("-")
    if not base:
        base = "sucursal"
    slug = base
    Model = instance.__class__
    i = 2
    qs = Model.objects.exclude(pk=instance.pk)
    while qs.filter(**{slug_field_name: slug}).exists():
        suf = f"-{i}"
        slug = (base[: max_length - len(suf)] + suf).strip("-")
        i += 1
    return slug


@receiver(pre_save, sender=Sucursal)
def sucursal_autoslug(sender, instance: "Sucursal", **kwargs):
    """
    - Si no hay slug: lo crea desde `nombre`.
    - Si hay slug pero cambió el `nombre`: lo regenera (manteniendo unicidad).
    """
    if not instance.slug:
        instance.slug = _unique_slugify(instance, instance.nombre)
        return

    if instance.pk:
        try:
            anterior = sender.objects.get(pk=instance.pk)
        except sender.DoesNotExist:
            anterior = None
        if anterior and anterior.nombre != instance.nombre:
            instance.slug = _unique_slugify(instance, instance.nombre)

# ==============================================================
# RESERVAS (con UTC + locales materializados)
# ==============================================================



class Reserva(models.Model):
    # ----- Estados -----
    PEND = "PEND"
    CONF = "CONF"
    CANC = "CANC"
    NOSH = "NOSH"
    ESTADOS = [
        (PEND, "Pendiente"),
        (CONF, "Confirmada"),
        (CANC, "Cancelada"),
        (NOSH, "No show"),
    ]

    # ----- Relaciones obligatorias -----
    cliente = models.ForeignKey("Cliente", on_delete=models.CASCADE)
    mesa = models.ForeignKey("Mesa", on_delete=models.CASCADE)

    # Acceso directo a sucursal (útil para filtros y analytics)
    # Se mantiene nullable/blank para no romper datos existentes; puedes
    # migrarlo a NOT NULL cuando todo esté materializado.
    sucursal = models.ForeignKey(
        "Sucursal",
        on_delete=models.CASCADE,
        related_name="reservas",
        null=True,
        blank=True,
    )

    # --------- LEGADO: fecha local (timezone-aware). Se conserva por compatibilidad. ---------
    fecha = models.DateTimeField()  # inicio (timezone-aware)

    # --------- NUEVOS CAMPOS: persistencia global y analítica local ---------
    inicio_utc = models.DateTimeField(null=True, blank=True, db_index=True)
    fin_utc = models.DateTimeField(null=True, blank=True)
    local_service_date = models.DateField(null=True, blank=True, db_index=True)
    local_inicio = models.DateTimeField(null=True, blank=True)
    local_fin = models.DateTimeField(null=True, blank=True)

    num_personas = models.PositiveSmallIntegerField(default=1)
    estado = models.CharField(max_length=4, choices=ESTADOS, default=PEND)

    folio = models.CharField(
        max_length=20, unique=True, default=generar_folio, editable=False, db_index=True
    )

    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)

    # llegada/confirmación en sucursal
    llego = models.BooleanField(default=False)
    checkin_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)

    # metadatos opcionales
    creada_por_staff = models.BooleanField(default=False)
    nombre_contacto = models.CharField(max_length=120, blank=True, default="")
    email_contacto = models.EmailField(blank=True, default="")
    telefono_contacto = models.CharField(max_length=30, blank=True, default="")

    # si se setea, la reserva terminó antes del fin teórico
    liberada_en = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = ReservaQuerySet.as_manager()  # <- activado para usar visible_for, etc.

    class Meta:
        ordering = ["-fecha", "-creado"]
        indexes = [
            models.Index(fields=["cliente", "estado"]),
            models.Index(fields=["fecha"]),
            models.Index(fields=["mesa", "fecha"]),
            models.Index(fields=["sucursal", "fecha"]),
            models.Index(fields=["inicio_utc"]),
            models.Index(fields=["local_service_date"]),
        ]

    # ---------------------- Representación ----------------------
    def __str__(self):
        try:
            suc = self.sucursal.nombre if self.sucursal_id else self.mesa.sucursal.nombre
            # Muestra hora local si la tenemos materializada; si no, usa fecha
            dt_show = self.local_inicio or self.fecha
            return f"{self.folio} - Mesa {self.mesa.numero} ({suc}) - {dt_show:%Y-%m-%d %H:%M}"
        except Exception:
            return f"{self.folio} - {self.fecha}"

    # ---------------------- Reglas/validaciones ----------------------
    def clean(self):
        """
        Validaciones de negocio antes de tocar la base de datos.
        No rompe flujos actuales: sólo da mensajes claros si algo viene mal.
        """
        # 1) Cliente obligatorio con mensaje claro (evita IntegrityError)
        if getattr(self, "cliente_id", None) is None:
            raise ValidationError({"cliente": "La reserva requiere un cliente (no puede ser nulo)."})

        # 2) Con USE_TZ=True, todos los DateTimeField deben ser timezone-aware
        if getattr(settings, "USE_TZ", False):
            for f in self._meta.fields:
                if isinstance(f, models.DateTimeField):
                    val = getattr(self, f.attname, None)
                    if val and is_naive(val):
                        raise ValidationError({f.name: "Debe ser timezone-aware con USE_TZ=True."})

    # ---------------------- Cálculos de tiempo ----------------------
    def fin_teorico(self, party: Optional[int] = None):
        p = int(party or getattr(self, "num_personas", 2) or 2)
        # Usa hora local si está materializada; si no, usa 'fecha'
        base_dt = self.local_inicio or self.fecha
        mins = int(booking_total_minutes(base_dt, p))
        return base_dt + timedelta(minutes=mins)

    def fin_efectivo(self, party: Optional[int] = None):
        ft = self.fin_teorico(party)
        lib = getattr(self, "liberada_en", None)
        if lib and lib >= (self.local_inicio or self.fecha):
            return min(ft, lib)
        return ft

    # ---------------------- Persistencia UTC/Local ----------------------
    def set_from_local(self, local_inicio_naive: datetime, dur_minutes: int):
        """
        Se le pasa una datetime *naive* que representa hora local de la sucursal.
        Convierte y rellena inicio_utc/fin_utc + materializados y 'fecha' legacy.
        """
        if not self.sucursal_id and self.mesa_id:
            # Asegura tener tz de sucursal
            self.sucursal_id = self.mesa.sucursal_id

        tz = self.sucursal.tz()
        local_dt = local_inicio_naive.replace(tzinfo=tz)
        self.local_inicio = local_dt
        self.local_fin = local_dt + timedelta(minutes=dur_minutes)
        self.local_service_date = local_dt.date()
        self.inicio_utc = local_dt.astimezone(ZoneInfo("UTC"))
        self.fin_utc = self.local_fin.astimezone(ZoneInfo("UTC"))
        # Mantén 'fecha' para compatibilidad de vistas antiguas
        self.fecha = local_dt

    def materialize_from_utc(self):
        """Si ya tienes inicio_utc/fin_utc, rellena campos locales y 'fecha' legacy."""
        if not self.inicio_utc:
            return
        tz = self.sucursal.tz()
        li = self.inicio_utc.astimezone(tz)
        self.local_inicio = li
        self.local_fin = self.fin_utc.astimezone(tz) if self.fin_utc else None
        self.local_service_date = li.date()
        self.fecha = li  # mantener compatibilidad con vistas existentes

    # ---------------------- Guardado ----------------------
    def save(self, *args, **kwargs):
        """
        - Autocompleta 'sucursal' desde 'mesa' si no viene informada.
        - Lanza validaciones antes del INSERT/UPDATE (evita errores de integridad).
        - Puedes desactivar validación con save(validate=False) para flujos legacy.
        """
        validate = kwargs.pop("validate", True)

        if not self.sucursal_id and self.mesa_id:
            self.sucursal_id = self.mesa.sucursal_id

        if validate:
            self.full_clean()

        return super().save(*args, **kwargs)



class CountryAdminScope(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="country_scopes")
    pais  = models.ForeignKey("Pais", on_delete=models.CASCADE, related_name="country_admins")
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("user", "pais")
        verbose_name = "Ámbito de país (admin)"
        verbose_name_plural = "Ámbitos de país (admins)"

    def __str__(self):
        return f"{self.user} @ {self.pais}"


