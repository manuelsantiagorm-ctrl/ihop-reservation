from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Cliente, Reserva
from .utils import conflicto_y_disponible, minutos_bloqueo_dinamico

ACTIVOS = ('PEND', 'CONF')  
# --------------------------
# Registro de cliente
# --------------------------
class ClienteRegistrationForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput)
    nombre = forms.CharField(max_length=100)
    telefono = forms.CharField(max_length=20, required=False)
    codigo_postal = forms.CharField(max_length=10, required=True, label='Código Postal')

    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'email', 'password', 'codigo_postal']

    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        if User.objects.filter(username=email).exists():
            raise ValidationError("Ese correo ya está registrado.")
        return email

    def save(self, commit=True):
        email = self.cleaned_data['email'].lower()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data['password'],
            first_name=self.cleaned_data['nombre'],
        )

        cliente = Cliente(
            user=user,
            nombre=self.cleaned_data['nombre'],
            email=email,
            telefono=self.cleaned_data.get('telefono', ''),
            codigo_postal=self.cleaned_data['codigo_postal'],
        )

        if commit:
            cliente.save()

        return user


# --------------------------
# Reserva
# --------------------------
class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['fecha', 'num_personas']
        widgets = {
            'fecha': forms.DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
                format='%Y-%m-%dT%H:%M'
            ),
            'num_personas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }

    def __init__(self, *args, **kwargs):
        self.mesa = kwargs.pop('mesa', None)
        self.cliente = kwargs.pop('cliente', None)
        super().__init__(*args, **kwargs)

        self.fields['fecha'].input_formats = ['%Y-%m-%dT%H:%M']

        now = timezone.localtime()
        end = now.replace(hour=23, minute=59, second=0, microsecond=0)
        self.fields['fecha'].widget.attrs.update({
            'min': now.strftime('%Y-%m-%dT%H:%M'),
            'max': end.strftime('%Y-%m-%dT%H:%M'),
        })

    def clean(self):
        cleaned = super().clean()
        fecha = cleaned.get('fecha')
        num_personas = cleaned.get('num_personas')

        if not self.mesa or not self.cliente:
            raise ValidationError("Error interno: falta información de cliente o mesa.")

        now_local = timezone.localtime()
        if not fecha:
            raise ValidationError("Debes indicar fecha y hora.")
        if fecha < now_local:
            raise ValidationError("No puedes reservar en una fecha/hora pasada.")
        if fecha.date() != now_local.date():
            raise ValidationError("Solo puedes reservar para HOY.")

        if num_personas is None or num_personas <= 0:
            raise ValidationError("Indica al menos 1 persona.")
        if num_personas > self.mesa.capacidad:
            raise ValidationError(f"La mesa soporta máximo {self.mesa.capacidad} personas.")

        # ⛔️ NUEVO: impedir más de una reservación activa
        # usa timezone.now() (UTC) para comparar con el campo datetime de DB
        if Reserva.objects.filter(
            cliente=self.cliente,
            estado__in=ACTIVOS,
            fecha__gte=timezone.now()
        ).exists():
            raise ValidationError(
                "Ya tienes una reservación activa. Cancélala o espera a que termine para hacer otra."
            )

        # Conflicto de mesa / bloqueo dinámico (deja esto después)
        conflicto, hora_disp = conflicto_y_disponible(self.mesa, fecha)
        if conflicto:
            minutos = minutos_bloqueo_dinamico(fecha)
            hora_local = timezone.localtime(hora_disp)
            hora_str = hora_local.strftime("%H:%M")
            raise ValidationError(
                f"La mesa está ocupada. Bloqueo de {minutos} min. Disponible nuevamente a las {hora_str}."
            )

        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.mesa = self.mesa
        obj.cliente = self.cliente
        obj.full_clean()
        if commit:
            obj.save()
        return obj