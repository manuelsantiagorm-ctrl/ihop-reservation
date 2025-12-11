# reservas/orders.py
from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.conf import settings
from django.utils import timezone

# IVA por defecto
IVA_DEFAULT = Decimal(getattr(settings, "IVA_RATE", "0.16"))


# ==========================================================
# =============== POS v1 (Order / OrderItem) ===============
# ==========================================================

class OrderStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    SUBMITTED = "SUBMITTED", "Enviada a cocina"
    IN_PREP = "IN_PREP", "En preparación"
    READY = "READY", "Lista"
    SERVED = "SERVED", "Servida"
    CLOSED = "CLOSED", "Cerrada"


class PaymentMethod(models.TextChoices):
    NONE = "NONE", "Sin pago"
    CASH = "CASH", "Efectivo"
    CARD = "CARD", "Tarjeta"
    MIXED = "MIXED", "Mixto"


class Order(models.Model):
    sucursal = models.ForeignKey("reservas.Sucursal", on_delete=models.PROTECT, related_name="orders")
    mesa     = models.ForeignKey("reservas.Mesa", on_delete=models.PROTECT, related_name="orders", null=True, blank=True)
    reserva  = models.ForeignKey("reservas.Reserva", on_delete=models.PROTECT, related_name="orders", null=True, blank=True)

    status = models.CharField(max_length=20, choices=OrderStatus.choices, default=OrderStatus.DRAFT)
    iva_rate = models.DecimalField(max_digits=4, decimal_places=2, default=IVA_DEFAULT)
    propina = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    subtotal_base = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    iva_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_bruto = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_con_propina = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.NONE)
    cerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="orders_cerrados")
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="orders_creados")

    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def _round2(self, x: Decimal) -> Decimal:
        return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @property
    def items(self):
        return self.orderitem_set.all()

    def compute_totals_live(self):
        bruto = sum((i.cantidad * i.precio_unitario for i in self.items if not i.cancelado), Decimal("0.00"))
        bruto = self._round2(Decimal(bruto))
        base = self._round2(bruto / (Decimal("1.00") + self.iva_rate))
        iva = self._round2(bruto - base)
        total = self._round2(bruto + self.propina)
        return {
            "subtotal_base": base,
            "iva_total": iva,
            "total_bruto": bruto,
            "total_con_propina": total,
        }

    def submit_to_kitchen(self):
        if self.status == OrderStatus.DRAFT:
            self.status = OrderStatus.SUBMITTED
            self.submitted_at = timezone.now()
            self.save(update_fields=["status", "submitted_at"])

    def close_and_free(self, user=None, payment_method=PaymentMethod.CASH):
        totals = self.compute_totals_live()
        self.subtotal_base = totals["subtotal_base"]
        self.iva_total = totals["iva_total"]
        self.total_bruto = totals["total_bruto"]
        self.total_con_propina = totals["total_con_propina"]
        self.payment_method = payment_method
        self.status = OrderStatus.CLOSED
        self.closed_at = timezone.now()
        if user and not self.cerrado_por:
            self.cerrado_por = user
        self.save()

    def __str__(self):
        return f"Order #{self.pk} ({self.get_status_display()})"


class OrderItem(models.Model):
    order = models.ForeignKey("reservas.Order", on_delete=models.CASCADE)
    nombre = models.CharField(max_length=120)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    cantidad = models.PositiveIntegerField(default=1)
    notas = models.CharField(max_length=240, blank=True, default="")
    enviado_a_cocina = models.BooleanField(default=False)
    cancelado = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def importe(self) -> Decimal:
        return (self.cantidad * self.precio_unitario).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def __str__(self):
        return f"{self.cantidad} x {self.nombre} (${self.precio_unitario})"


# =====================================================================
# == Variante “Orden / OrdenItem” (flujo nuevo modal + catálogo Menú) ==
# =====================================================================
class Orden(models.Model):
    # --- estados como constantes de clase ---
    ESTADO_ABIERTA   = "ABIERTA"
    ESTADO_EN_COCINA = "EN_COCINA"
    ESTADO_SERVIDA   = "SERVIDA"
    ESTADO_CERRADA   = "CERRADA"
    ESTADO_CANCELADA = "CANCELADA"

    ESTADO_CHOICES = [
        (ESTADO_ABIERTA,   "Abierta"),
        (ESTADO_EN_COCINA, "En cocina"),
        (ESTADO_SERVIDA,   "Servida"),
        (ESTADO_CERRADA,   "Cerrada"),
        (ESTADO_CANCELADA, "Cancelada"),
    ]

    # campo estado: SOLO UNA VEZ
    estado = models.CharField(
        max_length=20,
        choices=ESTADO_CHOICES,
        default=ESTADO_ABIERTA,
    )

    sucursal = models.ForeignKey(
        "reservas.Sucursal",
        on_delete=models.CASCADE,
        related_name="ordenes",
    )
    mesa = models.ForeignKey(
        "reservas.Mesa",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordenes",
    )
    reserva = models.ForeignKey(
        "reservas.Reserva",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ordenes",
    )

    total = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    notas = models.TextField(blank=True, default="")
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    creada_en = models.DateTimeField(default=timezone.now)
    actualizada_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creada_en"]

    def recomputar_total(self):
        total = sum(
            (it.subtotal or Decimal("0.00"))
            for it in self.items.all()
        )
        self.total = total
        self.save(update_fields=["total"])

    def __str__(self):
        return f"Orden #{self.id} · {self.sucursal} · {self.estado} · ${self.total}"

class OrdenItem(models.Model):
    ESTADO_PENDIENTE = "PENDIENTE"
    ESTADO_EN_PREP   = "EN_PREP"
    ESTADO_SERVIDO   = "SERVIDO"

    ESTADO_CHOICES = [
        (ESTADO_PENDIENTE, "Pendiente"),
        (ESTADO_EN_PREP, "En preparación"),
        (ESTADO_SERVIDO, "Servido"),
    ]

    orden = models.ForeignKey('reservas.Orden', on_delete=models.CASCADE, related_name="items")
    catalog_item = models.ForeignKey('reservas.CatalogItem', on_delete=models.SET_NULL, null=True, blank=True)

    codigo = models.CharField(max_length=30, blank=True, default="")
    nombre = models.CharField(max_length=200)
    categoria_nombre = models.CharField(max_length=120, blank=True, default="")
    precio_unit = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    cantidad = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    notas = models.CharField(max_length=200, blank=True, default="")
    creado_en = models.DateTimeField(auto_now_add=True)

    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default=ESTADO_PENDIENTE)
    cancelado = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    def save(self, *args, **kwargs):
        precio_base = self.precio if self.precio and self.precio > 0 else self.precio_unit
        self.subtotal = (precio_base or Decimal("0.00")) * (self.cantidad or 0)
        super().save(*args, **kwargs)

    @property
    def importe(self):
        return self.subtotal or Decimal("0.00")

    def es_editable(self):
        return self.estado == self.ESTADO_PENDIENTE and not self.cancelado

    def __str__(self):
        return f"{self.cantidad} × {self.nombre} (${self.precio or self.precio_unit})"
