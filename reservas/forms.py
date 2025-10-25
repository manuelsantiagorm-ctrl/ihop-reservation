# reservas/forms.py
from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone
from django.db import IntegrityError, transaction

from django.forms import inlineformset_factory
from .models import SucursalFoto
from .models import Cliente, Reserva, Sucursal, Mesa
from .utils import conflicto_y_disponible, generar_folio
from .emails import enviar_correo_reserva_confirmada
from django.utils.translation import gettext_lazy as _

# =========================
# Registro de cliente
# =========================
class ClienteRegistrationForm(forms.ModelForm):
    email = forms.EmailField(required=True)
    password = forms.CharField(widget=forms.PasswordInput)
    nombre = forms.CharField(max_length=100)
    telefono = forms.CharField(max_length=20, required=False)
    codigo_postal = forms.CharField(max_length=10, required=True, label="Código Postal")

    class Meta:
        model = Cliente
        fields = ["nombre", "telefono", "email", "password", "codigo_postal"]

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(username=email).exists():
            raise ValidationError("Ese correo ya está registrado.")
        return email

    def save(self, commit=True):
        email = self.cleaned_data["email"].lower()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=self.cleaned_data["password"],
            first_name=self.cleaned_data["nombre"],
        )
        cliente = Cliente(
            user=user,
            nombre=self.cleaned_data["nombre"],
            email=email,
            telefono=self.cleaned_data.get("telefono", ""),
            codigo_postal=self.cleaned_data["codigo_postal"],
        )
        if commit:
            cliente.save()
        return user


# =========================
# Form de Reserva (cliente)
# =========================
DATETIME_INPUT_FORMATS = ["%Y-%m-%dT%H:%M"]  # para <input type="datetime-local">

class ReservaForm(forms.ModelForm):
    class Meta:
        model = Reserva
        fields = ["fecha", "num_personas"]
        widgets = {
            "fecha": forms.DateTimeInput(
                attrs={"class": "form-control", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "num_personas": forms.NumberInput(attrs={"class": "form-control", "min": 1}),
        }

    def __init__(self, *args, **kwargs):
        self.mesa = kwargs.pop("mesa", None)
        self.cliente = kwargs.pop("cliente", None)
        super().__init__(*args, **kwargs)
        self.fields["fecha"].input_formats = DATETIME_INPUT_FORMATS

    def clean_fecha(self):
        fecha = self.cleaned_data.get("fecha")
        if not fecha:
            raise forms.ValidationError("Selecciona fecha y hora.")

        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha, timezone.get_current_timezone())

        ahora = timezone.now()

        if fecha < ahora:
            raise forms.ValidationError("La fecha/hora no puede estar en el pasado.")

        lead_min = int(getattr(settings, "RESERVA_LEAD_MIN", 15))
        if fecha < ahora + timezone.timedelta(minutes=lead_min):
            raise forms.ValidationError(
                f"Debes reservar con al menos {lead_min} minutos de anticipación."
            )

        max_dias = int(getattr(settings, "RESERVAS_MAX_DIAS_ADELANTE", 30))
        if fecha.date() > (timezone.localdate() + timezone.timedelta(days=max_dias)):
            raise forms.ValidationError(
                f"No puedes reservar con más de {max_dias} días de anticipación."
            )

        return fecha


# =========================
# Admin: reserva rápida por mesa (si la usas en algún detalle)
# =========================
class AdminReservaRapidaForm(forms.Form):
    fecha = forms.DateTimeField(
        label="Fecha y hora",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"],
    )
    asistentes = forms.IntegerField(label="Asistentes", min_value=1)
    nombre = forms.CharField(label="Nombre del cliente (opcional)", required=False)
    email = forms.EmailField(label="Email (opcional)", required=False)

    def __init__(self, *args, mesa: Mesa | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mesa = mesa

    def clean_asistentes(self):
        a = self.cleaned_data["asistentes"]
        if self.mesa and getattr(self.mesa, "capacidad", None) and a > self.mesa.capacidad:
            raise forms.ValidationError(f"La mesa tiene capacidad {self.mesa.capacidad}.")
        return a


# =========================
# Perfil de cliente
# =========================
class ClientePerfilForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "email", "telefono", "codigo_postal"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Tu nombre"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "tucorreo@dominio.com"}),
            "telefono": forms.TextInput(attrs={"class": "form-control", "placeholder": "Teléfono"}),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control", "placeholder": "CP"}),
        }


# =========================
# Walk-in (staff)
# =========================
# reservas/fo

# =========================
# Walk-in (staff)
# =========================
class WalkInReservaForm(forms.ModelForm):
    # Datos del cliente
    nombre_cliente = forms.CharField(label="Nombre del cliente", max_length=120)
    email_cliente = forms.EmailField(label="Email (opcional)", required=False)
    telefono_cliente = forms.CharField(label="Teléfono (opcional)", max_length=30, required=False)

    # Selecciones
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.all(), required=False, label="Sucursal")
    mesa = forms.ModelChoiceField(queryset=Mesa.objects.none(), label="Mesa")

    # Fecha/hora  🔧 forzamos formato de render "%Y-%m-%dT%H:%M"
    fecha = forms.DateTimeField(
        label="Fecha y hora",
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local"},
            format="%Y-%m-%dT%H:%M",   # <-- clave: render correcto para datetime-local
        ),
        input_formats=[
            "%Y-%m-%dT%H:%M",         # lo que envía el browser
            "%Y-%m-%d %H:%M",         # toleramos espacio por si acaso
        ],
    )

    class Meta:
        model = Reserva
        fields = ["sucursal", "mesa", "fecha", "num_personas"]

    def __init__(self, *args, **kwargs):
        """
        kwargs extra:
          - user (request.user) para filtrar sucursal si no es superuser
          - sucursal_pref (Sucursal) para preselección
        """
        self.user = kwargs.pop("user", None)
        suc_pref = kwargs.pop("sucursal_pref", None)
        super().__init__(*args, **kwargs)

        # 🔧 Asegurar formato y paso del widget siempre
        self.fields["fecha"].widget.format = "%Y-%m-%dT%H:%M"
        self.fields["fecha"].widget.attrs["step"] = 60  # 1 min, evita segundos

        # Clases Bootstrap básicas
        for name in ["nombre_cliente", "email_cliente", "telefono_cliente", "fecha", "num_personas"]:
            if name in self.fields:
                cur = self.fields[name].widget.attrs.get("class", "")
                self.fields[name].widget.attrs["class"] = (cur + " form-control").strip()
        for name in ["sucursal", "mesa"]:
            if name in self.fields:
                cur = self.fields[name].widget.attrs.get("class", "")
                self.fields[name].widget.attrs["class"] = (cur + " form-select").strip()

        # Staff no superuser => sucursal fija del PerfilAdmin
        suc = None
        if self.user and not getattr(self.user, "is_superuser", False):
            from .models import PerfilAdmin
            try:
                pa = PerfilAdmin.objects.get(user=self.user)
                self.fields["sucursal"].queryset = Sucursal.objects.filter(pk=pa.sucursal_asignada_id)
                self.fields["sucursal"].initial = pa.sucursal_asignada_id
                self.fields["sucursal"].widget = forms.HiddenInput()
                suc = pa.sucursal_asignada
            except PerfilAdmin.DoesNotExist:
                self.fields["sucursal"].queryset = Sucursal.objects.none()
                suc = None
        else:
            # Superuser
            if suc_pref:
                self.fields["sucursal"].initial = suc_pref.id
                suc = suc_pref

        # Mesas por sucursal
        if (self.data.get("sucursal") or self.fields["sucursal"].initial):
            try:
                suc_id = int(self.data.get("sucursal") or self.fields["sucursal"].initial)
                self.fields["mesa"].queryset = Mesa.objects.filter(sucursal_id=suc_id).order_by("numero")
            except Exception:
                self.fields["mesa"].queryset = Mesa.objects.none()
        elif suc:
            self.fields["mesa"].queryset = Mesa.objects.filter(sucursal=suc).order_by("numero")
        else:
            self.fields["mesa"].queryset = Mesa.objects.none()

        # Fecha por defecto (redondeada al paso y sin segundos)
        if not self.initial.get("fecha") and not self.data.get("fecha"):
            tz = timezone.get_current_timezone()
            now = timezone.now().astimezone(tz).replace(second=0, microsecond=0)
            step = int(getattr(settings, "RESERVA_PASO_MINUTOS", 15))
            extra = (step - (now.minute % step)) % step
            self.initial["fecha"] = (now + timezone.timedelta(minutes=extra))

    def clean_fecha(self):
        dt = self.cleaned_data["fecha"]
        tz = timezone.get_current_timezone()
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, tz)
        # 🔧 garantizamos sin segundos al guardar/validar
        return dt.replace(second=0, microsecond=0)

    def clean(self):
        cleaned = super().clean()
        mesa = cleaned.get("mesa")
        fecha = cleaned.get("fecha")
        num = cleaned.get("num_personas") or 1
        sucursal = cleaned.get("sucursal")

        if not mesa or not fecha:
            return cleaned

        # Mesa debe pertenecer a la sucursal seleccionada (si aplica)
        if sucursal and mesa.sucursal_id != sucursal.id:
            self.add_error("mesa", "La mesa no pertenece a la sucursal seleccionada.")
            return cleaned

        # Capacidad
        if getattr(mesa, "capacidad", None) and num > mesa.capacidad:
            self.add_error("num_personas", f"La mesa admite hasta {mesa.capacidad} personas.")

        # Choque con reservas de la mesa
        hay, hasta = conflicto_y_disponible(mesa, fecha)
        if hay:
            self.add_error(
                "fecha",
                f"Choque: la mesa está ocupada hasta las {hasta.astimezone(timezone.get_current_timezone()).strftime('%H:%M')}."
            )
        return cleaned

    def save(self, commit=True):
        # ... (tu save queda igual)
        reserva = super().save(commit=False)
        email = (self.cleaned_data.get("email_cliente") or "").strip()
        nombre = self.cleaned_data.get("nombre_cliente").strip()
        tel = (self.cleaned_data.get("telefono_cliente") or "").strip()

        if email:
            cliente, _ = Cliente.objects.get_or_create(
                email=email,
                defaults={"nombre": nombre, "telefono": tel}
            )
            to_update = []
            if not getattr(cliente, "nombre", "") and nombre:
                cliente.nombre = nombre
                to_update.append("nombre")
            if tel and not getattr(cliente, "telefono", ""):
                cliente.telefono = tel
                to_update.append("telefono")
            if to_update:
                cliente.save(update_fields=to_update)
        else:
            cliente = Cliente.objects.create(nombre=nombre, telefono=tel or "")

        reserva.cliente = cliente
        reserva.estado = "CONF"

        if not getattr(reserva, "folio", ""):
            reserva.folio = generar_folio(reserva)

        if commit:
            for _ in range(5):
                try:
                    with transaction.atomic():
                        reserva.save()
                    break
                except IntegrityError:
                    reserva.folio = generar_folio(reserva)
            else:
                raise

            if email:
                try:
                    enviar_correo_reserva_confirmada(reserva, bcc_sucursal=True)
                except Exception:
                    pass

        return reserva


# reservas/forms.py
# reservas/forms.py
from django import forms
from django.forms import inlineformset_factory

from .models import Sucursal, SucursalFoto


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = [
            "nombre", "direccion", "codigo_postal",
            "portada", "portada_alt",
            "cocina", "precio_nivel", "rating", "reviews",
            "recomendado", "activo",
        ]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "direccion": forms.TextInput(attrs={"class": "form-control"}),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control"}),
            "portada": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "portada_alt": forms.TextInput(attrs={"class": "form-control"}),
            "cocina": forms.TextInput(attrs={"class": "form-control"}),
            "precio_nivel": forms.TextInput(attrs={"class": "form-control", "placeholder": "$, $$, $$$, $$$$"}),
            "rating": forms.NumberInput(attrs={"class": "form-control", "step": "0.1", "min": "0", "max": "5"}),
            "reviews": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
            "recomendado": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class SucursalFotoForm(forms.ModelForm):
    class Meta:
        model = SucursalFoto
        fields = ["imagen", "alt", "orden"]
        widgets = {
            "imagen": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "alt": forms.TextInput(attrs={"class": "form-control"}),
            "orden": forms.NumberInput(attrs={"class": "form-control", "min": "0"}),
        }


SucursalFotoFormSet = inlineformset_factory(
    parent_model=Sucursal,
    model=SucursalFoto,
    form=SucursalFotoForm,
    extra=1,
    can_delete=True,
)



