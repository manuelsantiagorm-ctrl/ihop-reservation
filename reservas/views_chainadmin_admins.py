# reservas/views_chainadmin_admins.py
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from .utils_auth import user_allowed_countries
from .models import CountryAdminScope  # ⬅️ ESTE ES EL QUE FALTA

from collections import defaultdict, OrderedDict
from .mixins import ChainOwnerRequiredMixin
from .models import PerfilAdmin, Sucursal, ChainOwnerPaisRole
from .forms_chainadmin_admins import (
    BranchAdminCreateForm,
    BranchAdminUpdateForm,
    BranchAdminPasswordForm,
)

User = get_user_model()


def _branchadmin_qs():
    """
    Base: usuarios con is_staff y en el grupo 'BranchAdmin'.
    (Con .distinct() por si el usuario aparece en múltiples grupos.)
    """
    return (
        User.objects.filter(is_staff=True, groups__name="BranchAdmin")
        .order_by("username")
        .distinct()
    )


def _user_allowed_paises_ids(user):
    """
    Devuelve:
      - None  -> sin filtro (superuser)
      - []    -> sin países asignados (verá vacío)
      - [ids] -> países permitidos
    """
    if getattr(user, "is_superuser", False):
        return None
    paises = list(
        ChainOwnerPaisRole.objects.filter(user=user, activo=True).values_list("pais_id", flat=True)
    )
    return paises


class ChainAdminAdminsListView(ChainOwnerRequiredMixin, View):
    """
    Lista de Branch Admins, filtrada por los países permitidos del usuario.
    (Antes mostraba admins de otros países y, además, podía auto-crear perfiles con Sucursal.first()).
    """
    template_name = "reservas/chainadmin/admins_list.html"

    def get(self, request):
        allowed_paises = _user_allowed_paises_ids(request.user)

        admins = (
            User.objects
            .filter(groups__name="BranchAdmin", is_staff=True)
            .select_related(
                "perfiladmin",
                "perfiladmin__sucursal_asignada",
                "perfiladmin__sucursal_asignada__pais",
            )
            .order_by("username")
            .distinct()
        )

        # 🔒 Filtro de país en servidor (si NO es superuser)
        if allowed_paises is not None:
            admins = admins.filter(perfiladmin__sucursal_asignada__pais_id__in=allowed_paises)

        # ❌ Importante: NO auto-crear perfiles aquí (esto causaba ver CDMX en otros países).
        # La creación/ajuste de PerfilAdmin debe ocurrir en Create/Update con validación por país.

        return render(request, self.template_name, {"admins": admins})


class ChainAdminAdminsCreateView(ChainOwnerRequiredMixin, View):
    template_name = "reservas/chainadmin/admin_form.html"

    def get(self, request):
        form = BranchAdminCreateForm()
        # Limitar choices de sucursal según país (si el form tiene ese campo)
        allowed_paises = _user_allowed_paises_ids(request.user)
        if not request.user.is_superuser and hasattr(form, "fields") and "sucursal_asignada" in form.fields:
            form.fields["sucursal_asignada"].queryset = Sucursal.objects.filter(
                pais_id__in=(allowed_paises or [])
            )
        return render(request, self.template_name, {"form": form, "mode": "create"})

    def post(self, request):
        form = BranchAdminCreateForm(request.POST)
        allowed_paises = _user_allowed_paises_ids(request.user)

        # Reaplicar el filtro de queryset por seguridad de servidor
        if not request.user.is_superuser and hasattr(form, "fields") and "sucursal_asignada" in form.fields:
            form.fields["sucursal_asignada"].queryset = Sucursal.objects.filter(
                pais_id__in=(allowed_paises or [])
            )

        if form.is_valid():
            # Validación extra de servidor (si el form no trae el filtro)
            suc = form.cleaned_data.get("sucursal_asignada")
            if not request.user.is_superuser and allowed_paises is not None:
                if not suc or not suc.pais_id or suc.pais_id not in allowed_paises:
                    form.add_error("sucursal_asignada", "No puedes asignar administradores a sucursales fuera de tu país.")
                    return render(request, self.template_name, {"form": form, "mode": "create"})

            user = form.save()
            messages.success(request, f"Administrador '{user.username}' creado correctamente.")
            return redirect(reverse("reservas:chainadmin_admins"))

        return render(request, self.template_name, {"form": form, "mode": "create"})


class ChainAdminAdminsUpdateView(ChainOwnerRequiredMixin, View):
    template_name = "reservas/chainadmin/admin_form.html"

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        form = BranchAdminUpdateForm(user_instance=user)

        # Limitar choices por país si aplica
        allowed_paises = _user_allowed_paises_ids(request.user)
        if not request.user.is_superuser and hasattr(form, "fields") and "sucursal_asignada" in form.fields:
            form.fields["sucursal_asignada"].queryset = Sucursal.objects.filter(
                pais_id__in=(allowed_paises or [])
            )

        return render(
            request,
            self.template_name,
            {"form": form, "mode": "edit", "user_obj": user},
        )

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        form = BranchAdminUpdateForm(request.POST, user_instance=user)

        allowed_paises = _user_allowed_paises_ids(request.user)
        if not request.user.is_superuser and hasattr(form, "fields") and "sucursal_asignada" in form.fields:
            form.fields["sucursal_asignada"].queryset = Sucursal.objects.filter(
                pais_id__in=(allowed_paises or [])
            )

        if form.is_valid():
            suc = form.cleaned_data.get("sucursal_asignada")
            if not request.user.is_superuser and allowed_paises is not None:
                if not suc or not suc.pais_id or suc.pais_id not in allowed_paises:
                    form.add_error("sucursal_asignada", "No puedes mover administradores a sucursales fuera de tu país.")
                    return render(request, self.template_name, {"form": form, "mode": "edit", "user_obj": user})

            form.save()
            messages.success(request, f"Administrador '{user.username}' actualizado.")
            return redirect(reverse("reservas:chainadmin_admins"))

        return render(request, self.template_name, {"form": form, "mode": "edit", "user_obj": user})


class ChainAdminAdminsPasswordView(ChainOwnerRequiredMixin, View):
    template_name = "reservas/chainadmin/admin_password.html"

    def get(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        return render(request, self.template_name, {"form": BranchAdminPasswordForm(), "user_obj": user})

    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        form = BranchAdminPasswordForm(request.POST)
        if form.is_valid():
            user.set_password(form.cleaned_data["password1"])
            user.save()
            messages.success(request, f"Contraseña de '{user.username}' actualizada.")
            return redirect(reverse("reservas:chainadmin_admins"))
        return render(request, self.template_name, {"form": form, "user_obj": user})


class ChainAdminAdminsToggleActiveView(ChainOwnerRequiredMixin, View):
    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)

        # Solo puede togglear admins dentro de sus países
        allowed_paises = _user_allowed_paises_ids(request.user)
        if allowed_paises is not None:  # no es superuser
            try:
                pa = PerfilAdmin.objects.select_related("sucursal_asignada", "sucursal_asignada__pais").get(user=user)
                suc = pa.sucursal_asignada
            except PerfilAdmin.DoesNotExist:
                suc = None
            if not suc or not suc.pais_id or suc.pais_id not in allowed_paises:
                messages.error(request, "No puedes cambiar el estado de un admin fuera de tu país.")
                return redirect(reverse("reservas:chainadmin_admins"))

        user.is_active = not user.is_active
        user.save()
        # sincronizar perfil si existe
        try:
            pa = PerfilAdmin.objects.get(user=user)
            pa.activo = user.is_active
            pa.save()
        except PerfilAdmin.DoesNotExist:
            pass
        messages.success(request, f"Estado de '{user.username}' cambiado a {'activo' if user.is_active else 'inactivo'}.")
        return redirect(reverse("reservas:chainadmin_admins"))



# === NUEVO: Lista global agrupada por país ===
from collections import defaultdict, OrderedDict

class ChainAdminAdminsAllView(ChainOwnerRequiredMixin, View):
    """
    Muestra TODOS los Branch Admins agrupados por país.
    - Si es superuser: ve todos los países.
    - Si es ChainOwner de países: ve solo los suyos.
    """
    template_name = "reservas/chainadmin/admins_all.html"

    def get(self, request):
        allowed_paises = _user_allowed_paises_ids(request.user)  # None => superuser (sin filtro)

        qs = (
            User.objects
            .filter(groups__name="BranchAdmin", is_staff=True)
            .select_related("perfiladmin", "perfiladmin__sucursal_asignada", "perfiladmin__sucursal_asignada__pais")
            .order_by("username")
            .distinct()
        )
        if allowed_paises is not None:
            qs = qs.filter(perfiladmin__sucursal_asignada__pais_id__in=allowed_paises)

        # Agrupar por país
        grouped = defaultdict(list)
        for u in qs:
            pais = getattr(getattr(getattr(u, "perfiladmin", None), "sucursal_asignada", None), "pais", None)
            pais_nombre = getattr(pais, "nombre", "— Sin país —")
            grouped[pais_nombre].append(u)

        # Orden alfabético por país
        grouped_ordered = OrderedDict(sorted(grouped.items(), key=lambda x: x[0].lower()))

        return render(request, self.template_name, {
            "grouped": grouped_ordered,
        })


# === NUEVO: Detalle de un admin + admins del mismo país ===
class ChainAdminAdminDetailView(ChainOwnerRequiredMixin, View):
    template_name = "reservas/chainadmin/admin_detail.html"

    def get(self, request, user_id):
        u = get_object_or_404(
            User.objects.select_related(
                "perfiladmin",
                "perfiladmin__sucursal_asignada",
                "perfiladmin__sucursal_asignada__pais",
            ),
            pk=user_id, groups__name="BranchAdmin", is_staff=True
        )

        # Candado de país (si no es superuser)
        allowed_paises = _user_allowed_paises_ids(request.user)
        pais_id = getattr(getattr(getattr(u, "perfiladmin", None), "sucursal_asignada", None), "pais_id", None)
        if allowed_paises is not None and pais_id not in allowed_paises:
            messages.error(request, "No puedes ver administradores de otro país.")
            return redirect(reverse("reservas:chainadmin_admins"))

        # Peers del mismo país (excluyendo al actual)
        peers = User.objects.filter(
            groups__name="BranchAdmin", is_staff=True,
            perfiladmin__sucursal_asignada__pais_id=pais_id
        ).exclude(pk=u.pk).select_related(
            "perfiladmin", "perfiladmin__sucursal_asignada"
        ).order_by("username").distinct()

        return render(request, self.template_name, {
            "admin_obj": u,
            "peers": peers,
        })




# === NUEVO: Referentes (Admins de país) agrupados por país ===

class CountryAdminsAllView(View):
    template_name = "reservas/chainadmin/country_admins_all.html"

    def get(self, request):
        allowed = user_allowed_countries(request.user)  # QS de Pais

        scope_qs = (
            CountryAdminScope.objects
            .select_related("user", "pais")
            .order_by("pais__nombre", "user__username")
        )
        if not request.user.is_superuser:
            scope_qs = scope_qs.filter(pais__in=allowed)

        grouped = defaultdict(list)
        for r in scope_qs:
            grouped[r.pais.nombre].append(r.user)

        grouped = OrderedDict(sorted(grouped.items(), key=lambda kv: kv[0].lower()))
        return render(request, self.template_name, {"grouped": grouped})


User = get_user_model()

class CountryAdminDetailView(View):
    template_name = "reservas/chainadmin/country_admin_detail.html"

    def get(self, request, user_id):
        u = get_object_or_404(User, pk=user_id)
        allowed = user_allowed_countries(request.user)
        scope_qs = CountryAdminScope.objects.select_related("pais").filter(user=u)
        if not request.user.is_superuser:
            scope_qs = scope_qs.filter(pais__in=allowed)
        paises = [s.pais for s in scope_qs]
        return render(request, self.template_name, {"admin_user": u, "paises": paises})
