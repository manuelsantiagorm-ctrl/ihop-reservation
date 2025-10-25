# reservas/views_chainadmin.py
from collections import defaultdict, OrderedDict

from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import Sucursal
from .forms_sucursales import SucursalForm
from .mixins import CountryScopedQuerysetMixin, CountryScopedObjectMixin
from .utils_auth import user_allowed_countries


# ---------------------------------------------------------------
# Helpers locales
# ---------------------------------------------------------------

def _allowed_country_ids(user):
    """
    Normaliza user_allowed_countries(user) a un set de IDs de país.
    Puede venir como QuerySet de Pais, lista de Pais, o lista de IDs.
    """
    paises = user_allowed_countries(user)
    try:
        return set(paises.values_list("id", flat=True))
    except Exception:
        # lista de objetos o ids
        ids = []
        for p in paises or []:
            ids.append(getattr(p, "id", p))
        return set(ids)


# ===============================================================
# LISTAR SUCURSALES
# ===============================================================

class ChainAdminSucursalListView(CountryScopedQuerysetMixin, ListView):
    template_name = "reservas/chainadmin/sucursales_list.html"
    model = Sucursal
    context_object_name = "sucursales"
    paginate_by = None  # agrupamos por país, mejor sin paginar

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("pais")
            .order_by("pais__nombre", "nombre")
        )
        # Filtro opcional por ?pais=<id>
        pais_id = self.request.GET.get("pais")
        if pais_id:
            qs = qs.filter(pais_id=pais_id)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        # Países permitidos (para dropdowns)
        allowed = user_allowed_countries(self.request.user)
        ctx["allowed_countries"] = allowed
        # ids para usar en templates (condiciones rápidas)
        try:
            ctx["allowed_pais_ids"] = list(allowed.values_list("id", flat=True))
        except Exception:
            ctx["allowed_pais_ids"] = [getattr(p, "id", p) for p in (allowed or [])]

        # Agrupar por país -> OrderedDict alfabético
        grouped = defaultdict(list)
        for s in ctx["object_list"]:
            grouped[s.pais.nombre].append(s)
        ctx["grouped"] = OrderedDict(sorted(grouped.items(), key=lambda kv: kv[0].lower()))
        return ctx


# ===============================================================
# CREAR SUCURSAL
# ===============================================================

class ChainAdminSucursalCreateView(CreateView):
    template_name = "reservas/chainadmin/sucursal_form.html"
    model = Sucursal
    form_class = SucursalForm
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # el form puede usar request para limitar choices de País
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        allowed_ids = _allowed_country_ids(user)

        # Si solo tiene un país y el campo viene vacío, forzarlo
        if len(allowed_ids) == 1 and not form.cleaned_data.get("pais"):
            form.instance.pais_id = next(iter(allowed_ids))

        # Seguridad: impedir crear en país no permitido
        # (el campo del form normalmente es 'pais', no 'pais_id')
        selected_pais = form.cleaned_data.get("pais")
        selected_id = getattr(selected_pais, "id", selected_pais)
        if not user.is_superuser and selected_id not in allowed_ids:
            form.add_error("pais", _("No tienes permiso para crear sucursales en ese país."))
            return self.form_invalid(form)

        messages.success(self.request, _("Sucursal creada correctamente."))
        return super().form_valid(form)


# ===============================================================
# EDITAR SUCURSAL
# ===============================================================

class ChainAdminSucursalUpdateView(CountryScopedObjectMixin, UpdateView):
    template_name = "reservas/chainadmin/sucursal_form.html"
    model = Sucursal
    form_class = SucursalForm
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request
        return kwargs

    def form_valid(self, form):
        user = self.request.user
        allowed_ids = _allowed_country_ids(user)

        selected_pais = form.cleaned_data.get("pais")
        selected_id = getattr(selected_pais, "id", selected_pais)
        if not user.is_superuser and selected_id not in allowed_ids:
            form.add_error("pais", _("No tienes permiso para modificar sucursales de ese país."))
            return self.form_invalid(form)

        messages.success(self.request, _("Sucursal actualizada correctamente."))
        return super().form_valid(form)


# ===============================================================
# ELIMINAR SUCURSAL
# ===============================================================

class ChainAdminSucursalDeleteView(CountryScopedObjectMixin, DeleteView):
    template_name = "reservas/chainadmin/sucursal_confirm_delete.html"
    model = Sucursal
    success_url = reverse_lazy("reservas:chainadmin_sucursales")

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, _("Sucursal eliminada."))
        return super().delete(request, *args, **kwargs)
