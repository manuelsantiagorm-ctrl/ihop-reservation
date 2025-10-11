# reservas/forms_branchadmin.py
from django import forms
from django.contrib.auth import get_user_model
from .models import Sucursal, PerfilAdmin

User = get_user_model()

class BranchAdminCreateForm(forms.Form):
    # Datos del usuario
    username = forms.CharField(max_length=150, help_text="Identificador único")
    email = forms.EmailField(required=True)
    first_name = forms.CharField(label="Nombre", required=False)
    last_name = forms.CharField(label="Apellidos", required=False)
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)

    # Asignación
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.all())
    is_active = forms.BooleanField(label="Activo", required=False, initial=True)

    def clean_username(self):
        u = self.cleaned_data["username"]
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("Ese username ya existe.")
        return u

    def clean(self):
        cd = super().clean()
        p1, p2 = cd.get("password1"), cd.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        return cd


class BranchAdminUpdateForm(forms.Form):
    email = forms.EmailField(required=True)
    first_name = forms.CharField(label="Nombre", required=False)
    last_name = forms.CharField(label="Apellidos", required=False)
    sucursal = forms.ModelChoiceField(queryset=Sucursal.objects.all())
    is_active = forms.BooleanField(label="Activo", required=False)

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user_obj")
        super().__init__(*args, **kwargs)

    def save(self):
        u = self.user
        u.email = self.cleaned_data["email"]
        u.first_name = self.cleaned_data["first_name"]
        u.last_name = self.cleaned_data["last_name"]
        u.is_active = self.cleaned_data["is_active"]
        u.save()

        # Actualiza/crea PerfilAdmin
        suc = self.cleaned_data["sucursal"]
        pa, _ = PerfilAdmin.objects.get_or_create(user=u)
        # Asumo campo 'sucursal' en PerfilAdmin
        if hasattr(pa, "sucursal_id"):
            pa.sucursal = suc
        pa.save()
        return u


class BranchAdminPasswordForm(forms.Form):
    password1 = forms.CharField(label="Nueva contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)

    def clean(self):
        cd = super().clean()
        if cd.get("password1") != cd.get("password2"):
            self.add_error("password2", "No coinciden.")
        return cd
