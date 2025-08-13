from django.db import models
from django.contrib.auth.models import User


# ==========================
# SUCURSAL
# ==========================
class Sucursal(models.Model):
    nombre = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)
    codigo_postal = models.CharField(max_length=10)
    total_mesas = models.PositiveIntegerField(default=20)

    def __str__(self):
        return self.nombre


# ==========================
# MESA
# ==========================
class Mesa(models.Model):
    ESTADOS = [
        ('disponible', 'Disponible'),
        ('reservada', 'Reservada'),
        ('ocupada', 'Ocupada'),
    ]

    sucursal = models.ForeignKey(Sucursal, on_delete=models.CASCADE, related_name='mesas')
    numero = models.PositiveIntegerField()
    capacidad = models.PositiveIntegerField(default=4)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='disponible')

    def __str__(self):
        return f"Mesa {self.numero} - {self.sucursal.nombre}"


# ==========================
# CLIENTE
# ==========================
class Cliente(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    email = models.EmailField()
    telefono = models.CharField(max_length=20, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)

    def __str__(self):
        return self.nombre


# ==========================
# RESERVA
# ==========================
class Reserva(models.Model):
    ESTADOS = [
        ('CONF', 'Confirmada'),
        ('PEND', 'Pendiente'),
        ('CANC', 'Cancelada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, related_name='reservas')
    mesa = models.ForeignKey(Mesa, on_delete=models.CASCADE, related_name='reservas')
    fecha = models.DateTimeField()
    num_personas = models.PositiveIntegerField()
    estado = models.CharField(max_length=4, choices=ESTADOS, default='PEND')
    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.cliente.nombre} — {self.mesa} — {self.fecha.strftime('%d/%m/%Y %H:%M')} — {self.get_estado_display()}"

    class Meta:
        ordering = ['-fecha']
        
    class Meta:
        indexes = [
            models.Index(fields=["mesa", "fecha"]),
        ]


# ==========================
# PERFIL ADMINISTRADOR
# ==========================
class PerfilAdmin(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    sucursal_asignada = models.ForeignKey(Sucursal, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} — {self.sucursal_asignada}"
