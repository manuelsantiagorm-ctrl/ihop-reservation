from django import forms
from django.contrib.auth.models import User
from .models import Cliente, Reserva, Mesa, Sucursal
from django.utils.timezone import now
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.forms import DateTimeInput


class ClienteRegistrationForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput)
    nombre = forms.CharField(max_length=100)
    telefono = forms.CharField(max_length=20, required=False)
    codigo_postal = forms.CharField(max_length=10, required=True, label='Código Postal')

    class Meta:
        model = Cliente
        fields = ['nombre', 'telefono', 'email', 'password', 'codigo_postal']

    def save(self, commit=True):
        user = User.objects.create_user(
            username=self.cleaned_data['email'],
            email=self.cleaned_data['email'],
            password=self.cleaned_data['password'],
            first_name=self.cleaned_data['nombre'],
        )

        cliente = Cliente(
            user=user,
            nombre=self.cleaned_data['nombre'],
            email=self.cleaned_data['email'],
            telefono=self.cleaned_data['telefono'],
            codigo_postal=self.cleaned_data['codigo_postal']
        )

        if commit:
            cliente.save()

        return user


class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ['fecha', 'num_personas']
        widgets = {
            'fecha': DateTimeInput(
                attrs={'type': 'datetime-local', 'class': 'form-control'},
                format='%Y-%m-%dT%H:%M'  # <-- formato correcto para datetime-local
            ),
            'num_personas': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        self.mesa = kwargs.pop('mesa', None)
        self.cliente = kwargs.pop('cliente', None)
        super().__init__(*args, **kwargs)

        # 🔥 línea clave para evitar error de formato
        self.fields['fecha'].input_formats = ['%Y-%m-%dT%H:%M']

   def clean(self):
    cleaned_data = super().clean()
    fecha = cleaned_data.get('fecha')
    num_personas = cleaned_data.get('num_personas')

    if not self.mesa or not self.cliente:
        raise ValidationError("Error interno: falta información de cliente o mesa.")

    if fecha and fecha < now().replace(second=0, microsecond=0):
        raise ValidationError("No puedes reservar en una fecha u hora pasada.")

    if num_personas and self.mesa.capacidad < num_personas:
        raise ValidationError(f"La mesa solo admite hasta {self.mesa.capacidad} personas.")

    inicio = fecha
    fin = fecha + timedelta(hours=1)
    conflicto = Reserva.objects.filter(
        mesa=self.mesa,
        fecha__lt=fin,
        fecha__gte=inicio,
        estado__in=['PEND', 'CONF']
    ).exists()
    if conflicto:
        raise ValidationError("La mesa ya está ocupada en ese horario. Elige otra hora o mesa.")

    reserva_existente = Reserva.objects.filter(
        cliente=self.cliente,
        estado__in=['PEND', 'CONF']
    ).exists()
    if reserva_existente:
        raise ValidationError("Ya tienes una reservación activa. Cancélala para hacer una nueva.")

    return cleaned_data
