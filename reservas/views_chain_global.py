# reservas/views_chain_global.py
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db import transaction
from django.db.models import Count  # <- IMPORT CLAVE
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import TemplateView, CreateView, View

from .models import Pais, ChainOwnerPaisRole, Sucursal

User = get_user_model()


class SuperuserRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_superuser


class ChainGlobalDashboardView(LoginRequiredMixin, SuperuserRequiredMixin, TemplateView):
    template_name = "chain_global/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["roles"] = (
            ChainOwnerPaisRole.objects
            .select_related("user", "pais")
            .order_by("-activo", "pais__nombre", "user__email")
        )
        # KPIs rápidos por país (sucursales por país)
        ctx["paises"] = Pais.objects.order_by("nombre")
        ctx["sucursales_por_pais"] = (
            Sucursal.objects
            .values("pais__iso2", "pais__nombre")
            .order_by("pais__nombre")
            .annotate(total=Count("id"))
        )
        return ctx


class RoleCreateForm(forms.ModelForm):
    class Meta:
        model = ChainOwnerPaisRole
        fields = ["user", "pais", "activo"]


class ChainGlobalRoleCreateView(LoginRequiredMixin, SuperuserRequiredMixin, CreateView):
    model = ChainOwnerPaisRole
    form_class = RoleCreateForm
    template_name = "chain_global/role_form.html"
    success_url = reverse_lazy("reservas:chain_global_dashboard")

    def form_valid(self, form):
        messages.success(self.request, "Role creado/actualizado correctamente.")
        return super().form_valid(form)


class ChainGlobalRoleToggleActiveView(LoginRequiredMixin, SuperuserRequiredMixin, View):
    def post(self, request, pk):
        role = ChainOwnerPaisRole.objects.select_related("user", "pais").get(pk=pk)
        role.activo = not role.activo
        role.save(update_fields=["activo"])
        messages.success(
            request,
            f"Role de {role.user} en {role.pais.iso2} → {'ACTIVO' if role.activo else 'INACTIVO'}"
        )
        return redirect("reservas:chain_global_dashboard")


# ===================== Crear usuario + asignar rol país =====================

class CreateCountryAdminUserForm(forms.Form):
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    pais = forms.ModelChoiceField(label="País", queryset=Pais.objects.all())
    activo = forms.BooleanField(label="Activo", required=False, initial=True)
    is_staff = forms.BooleanField(label="Acceso admin (is_staff)", required=False, initial=True)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Ya existe un usuario con ese email.")
        return email


class CreateCountryAdminUserView(LoginRequiredMixin, SuperuserRequiredMixin, TemplateView):
    template_name = "chain_global/create_country_admin_user.html"
    success_url = reverse_lazy("reservas:chain_global_dashboard")
    form_class = CreateCountryAdminUserForm

    def get(self, request, *args, **kwargs):
        return self.render_to_response({"form": self.form_class()})

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        form = self.form_class(request.POST)
        if not form.is_valid():
            return self.render_to_response({"form": form})

        email = form.cleaned_data["email"].strip().lower()
        password = form.cleaned_data["password"]
        pais = form.cleaned_data["pais"]
        activo = form.cleaned_data["activo"]
        is_staff = form.cleaned_data["is_staff"]

        # Crear usuario no-superuser
        user = User.objects.create(
            username=email.split("@")[0],
            email=email,
            is_active=True,
            is_staff=is_staff,
            is_superuser=False,
        )
        user.set_password(password)
        user.save()

        # Asignar rol de país
        role, _ = ChainOwnerPaisRole.objects.get_or_create(user=user, pais=pais)
        role.activo = activo
        role.save(update_fields=["activo"])

        messages.success(
            request,
            f"Usuario {email} creado y asignado como ChainOwner de {pais.nombre}."
        )
        return redirect(self.success_url)
