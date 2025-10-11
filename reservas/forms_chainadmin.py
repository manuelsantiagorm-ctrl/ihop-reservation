# reservas/forms_chainadmin.py
from django import forms
from .models import Sucursal
from .utils_time import resolve_tz_from_latlng

class SucursalForm(forms.ModelForm):
    class Meta:
        model = Sucursal
        fields = (
            "nombre", "direccion", "codigo_postal",
            "pais", "timezone",
            "lat", "lng", "place_id",
            "recepcion_x", "recepcion_y",
            "portada", "portada_alt",
            "cocina", "precio_nivel",
            "administradores",
            "activo",
        )

    def clean(self):
        cleaned = super().clean()
        tz = (cleaned.get("timezone") or "").strip()
        lat = cleaned.get("lat")
        lng = cleaned.get("lng")

        # Si no hay timezone y sí hay lat/lng -> intenta resolver vía Google
        if not tz and lat is not None and lng is not None:
            tz_guess = resolve_tz_from_latlng(float(lat), float(lng))
            if tz_guess:
                cleaned["timezone"] = tz_guess  # lo rellenamos
        return cleaned
