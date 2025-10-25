from django import forms
from .models import Sucursal, Pais
from .utils_auth import user_allowed_countries  # helper para filtrar países por usuario


class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = [
            "nombre", "direccion", "codigo_postal", "pais", "timezone",
            "lat", "lng", "place_id",
            "recepcion_x", "recepcion_y", "precio_nivel", "cocina", "activo",
            "portada", "portada_alt", "administradores", "email_contacto",
        ]
        labels = {
            "nombre": "Nombre",
            "direccion": "Dirección",
            "codigo_postal": "Código postal",
            "pais": "País",
            "timezone": "Zona horaria (IANA)",
            "recepcion_x": "Recepción X",
            "recepcion_y": "Recepción Y",
            "precio_nivel": "Precio nivel",
            "cocina": "Cocina / concepto",
            "activo": "Activo",
            "portada": "Imagen de portada",
            "portada_alt": "Texto alternativo",
            "administradores": "Administradores de la sucursal",
            "email_contacto": "Correo de contacto",
        }
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "IHOP CDMX"
            }),
            "direccion": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Escribe y selecciona de Google Maps",
                "autocomplete": "off"
            }),
            "codigo_postal": forms.TextInput(attrs={"class": "form-control"}),
            "pais": forms.Select(attrs={"class": "form-select"}),
            "timezone": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "America/Mexico_City"
            }),

            "lat": forms.TextInput(attrs={
                "class": "form-control-plaintext border rounded px-2",
                "readonly": True
            }),
            "lng": forms.TextInput(attrs={
                "class": "form-control-plaintext border rounded px-2",
                "readonly": True
            }),
            "place_id": forms.TextInput(attrs={
                "class": "form-control-plaintext border rounded px-2",
                "readonly": True
            }),

            "recepcion_x": forms.NumberInput(attrs={"class": "form-control"}),
            "recepcion_y": forms.NumberInput(attrs={"class": "form-control"}),
            "precio_nivel": forms.Select(attrs={"class": "form-select"}),
            "cocina": forms.TextInput(attrs={
                "class": "form-control", "placeholder": "Americana • Desayunos"
            }),
            "activo": forms.CheckboxInput(attrs={"class": "form-check-input"}),

            "portada": forms.ClearableFileInput(attrs={"class": "form-control"}),
            "portada_alt": forms.TextInput(attrs={"class": "form-control"}),

            "administradores": forms.SelectMultiple(attrs={
                "class": "form-select", "size": 6
            }),
            "email_contacto": forms.EmailInput(attrs={"class": "form-control"}),
        }

    # -------------------------------------------------------------
    # Inicialización con control de países según usuario logueado
    # -------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)

        # 🔹 Asegura que haya países cargados y un label vacío
        self.fields["pais"].queryset = Pais.objects.all().order_by("nombre")
        self.fields["pais"].empty_label = "Selecciona un país"

        # 🔹 Si recibimos request, limitamos países al usuario logueado
        if request and request.user.is_authenticated:
            allowed = user_allowed_countries(request.user).order_by("nombre")
            self.fields["pais"].queryset = allowed

            # Si solo tiene un país disponible → autoseleccionar y bloquear
            if allowed.count() == 1 and not self.instance.pk:
                self.fields["pais"].initial = allowed.first().pk
                self.fields["pais"].widget.attrs["readonly"] = True
                self.fields["pais"].widget.attrs["disabled"] = True
