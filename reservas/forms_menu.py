# reservas/forms_menu.py
from django import forms
from django.utils.translation import gettext_lazy as _
from .models_menu import CatalogCategory, CatalogItem, CatalogComboComponent

class CategoryForm(forms.ModelForm):
    class Meta:
        model = CatalogCategory
        fields = ["nombre", "orden", "activo"]

class MenuItemForm(forms.ModelForm):
    class Meta:
        model = CatalogItem
        fields = [
            "codigo", "nombre", "categoria", "precio", "descripcion",
            "activo", "area_impresion", "imprimible",
            "es_combo", "precio_combo",
            "aplica_impuesto", "aplica_servicio",
        ]

    def clean_codigo(self):
        value = (self.cleaned_data.get("codigo") or "").strip().upper()
        if " " in value:
            raise forms.ValidationError(_("El código no debe contener espacios"))
        return value

class ComboComponentForm(forms.ModelForm):
    class Meta:
        model = CatalogComboComponent
        fields = ["item", "cantidad"]
        widgets = { "cantidad": forms.NumberInput(attrs={"min": 1}) }
