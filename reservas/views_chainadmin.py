# reservas/views_chainadmin.py
from django.contrib import messages
from django.urls import reverse_lazy
from django.shortcuts import redirect
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .mixins import ChainOwnerRequiredMixin, ChainScopeMixin
from .models import Sucursal
from .forms_chainadmin import SucursalForm


class ChainAdminSucursalListView(ChainOwnerRequiredMixin, ChainScopeMixin, ListView):
    template_name = "reservas/chainadmin/sucursales_list.html"
    model = Sucursal
    context_object_name = "sucursales"

    def get_queryset(self):
        # Superuser ve todas; ChainOwner País ve solo sus países.
        qs = super().get_queryset().select_related("pais").order_by("nombre")
        return self.chain_scope(qs, "pais_id")


class ChainAdminSucursalCreateView(ChainOwnerRequiredMixin, ChainScopeMixin, CreateView):
    template_name = "reservas/chainadmin/sucursal_form.html"
    model = Sucursal
    form_class = SucursalForm
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Si no es superuser, limita el combo de País a sus países asignados
        if not self.request.user.is_superuser and "pais" in form.fields:
            pais_ids = self.user_paises_ids()  # [] si no tiene o None si superuser
            form.fields["pais"].queryset = form.fields["pais"].queryset.filter(id__in=pais_ids or [])
        return form

    def form_valid(self, form):
        # Seguridad extra: si no es superuser, no permitir guardar fuera de su país
        if not self.request.user.is_superuser and form.cleaned_data.get("pais"):
            pais_ids = set(self.user_paises_ids() or [])
            if form.cleaned_data["pais"].id not in pais_ids:
                form.add_error("pais", _("No tienes permiso para crear sucursales en ese país."))
                return self.form_invalid(form)

        messages.success(self.request, _("Sucursal creada correctamente."))
        return super().form_valid(form)


class ChainAdminSucursalUpdateView(ChainOwnerRequiredMixin, ChainScopeMixin, UpdateView):
    template_name = "reservas/chainadmin/sucursal_form.html"
    model = Sucursal
    form_class = SucursalForm
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_queryset(self):
        # Asegura que solo pueda editar sucursales dentro de su alcance de país
        qs = super().get_queryset().select_related("pais")
        return self.chain_scope(qs, "pais_id")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Si no es superuser, limita el combo de País a sus países asignados
        if not self.request.user.is_superuser and "pais" in form.fields:
            pais_ids = self.user_paises_ids()
            form.fields["pais"].queryset = form.fields["pais"].queryset.filter(id__in=pais_ids or [])
        return form

    def form_valid(self, form):
        # Seguridad extra: no permitir mover la sucursal a un país fuera de su alcance
        if not self.request.user.is_superuser and form.cleaned_data.get("pais"):
            pais_ids = set(self.user_paises_ids() or [])
            if form.cleaned_data["pais"].id not in pais_ids:
                form.add_error("pais", _("No tienes permiso para modificar sucursales de ese país."))
                return self.form_invalid(form)

        messages.success(self.request, _("Sucursal actualizada."))
        return super().form_valid(form)


class ChainAdminSucursalDeleteView(ChainOwnerRequiredMixin, ChainScopeMixin, DeleteView):
    template_name = "reservas/chainadmin/sucursal_confirm_delete.html"
    model = Sucursal
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_queryset(self):
        # Solo permite borrar sucursales dentro de su alcance de país
        qs = super().get_queryset()
        return self.chain_scope(qs, "pais_id")

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, _("Sucursal eliminada."))
        return super().delete(request, *args, **kwargs)
