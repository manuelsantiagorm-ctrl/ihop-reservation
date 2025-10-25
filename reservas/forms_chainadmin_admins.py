# reservas/forms_chainadmin_admins.py
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import PerfilAdmin, Sucursal

User = get_user_model()


class BranchAdminCreateForm(forms.Form):
    username = forms.CharField(max_length=150, label="Usuario")
    email = forms.EmailField(label="Email")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Contraseña")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirmar contraseña")
    # Nota: el campo del modelo es sucursal_asignada
    sucursal_asignada = forms.ModelChoiceField(queryset=Sucursal.objects.all(), label="Sucursal")
    activo = forms.BooleanField(required=False, initial=True, label="Activo")

    def clean_username(self):
        u = self.cleaned_data["username"]
        if User.objects.filter(username=u).exists():
            raise ValidationError("Ese username ya existe.")
        return u

    def clean(self):
        cd = super().clean()
        if cd.get("password1") != cd.get("password2"):
            raise ValidationError("Las contraseñas no coinciden.")
        return cd

    @transaction.atomic
    def save(self):
        cd = self.cleaned_data
        user = User.objects.create_user(
            username=cd["username"],
            email=cd["email"],
            password=cd["password1"],
        )
        user.is_staff = True
        user.is_active = cd.get("activo", True)  # activo → User.is_active
        user.save()

        # Asegurar grupo BranchAdmin
        group, _ = Group.objects.get_or_create(name="BranchAdmin")
        user.groups.add(group)

        # PerfilAdmin: usar el nombre real del campo sucursal_asignada
        PerfilAdmin.objects.update_or_create(
            user=user,
            defaults={
                "sucursal_asignada": cd["sucursal_asignada"],
            },
        )
        return user


class BranchAdminUpdateForm(forms.Form):
    email = forms.EmailField(label="Email")
    sucursal_asignada = forms.ModelChoiceField(queryset=Sucursal.objects.all(), label="Sucursal")
    activo = forms.BooleanField(required=False, label="Activo")

    def __init__(self, *args, **kwargs):
        self.user_instance = kwargs.pop("user_instance")
        super().__init__(*args, **kwargs)

        # valores iniciales
        self.fields["email"].initial = self.user_instance.email
        self.fields["activo"].initial = self.user_instance.is_active
        try:
            pa = PerfilAdmin.objects.get(user=self.user_instance)
            self.fields["sucursal_asignada"].initial = pa.sucursal_asignada
        except PerfilAdmin.DoesNotExist:
            pass

    @transaction.atomic
    def save(self):
        cd = self.cleaned_data
        u = self.user_instance
        u.email = cd["email"]
        u.is_active = cd.get("activo", True)
        u.is_staff = True
        u.save()

        PerfilAdmin.objects.update_or_create(
            user=u,
            defaults={
                "sucursal_asignada": cd["sucursal_asignada"],
            },
        )

        # asegurar grupo
        group, _ = Group.objects.get_or_create(name="BranchAdmin")
        u.groups.add(group)
        return u


class BranchAdminPasswordForm(forms.Form):
    password1 = forms.CharField(widget=forms.PasswordInput, label="Nueva contraseña")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirmar contraseña")

    def clean(self):
        cd = super().clean()
        if cd.get("password1") != cd.get("password2"):
            raise ValidationError("Las contraseñas no coinciden.")
        return cd
