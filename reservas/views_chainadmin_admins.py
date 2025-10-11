# reservas/views_chainadmin_admins.py
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View

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
    template_name = "reservas/chainadmin/admins_list.html"

    def get(self, request):
        admins = _branchadmin_qs()
        # Traer perfiles en lote
        perfiles = {
            p.user_id: p
            for p in PerfilAdmin.objects.select_related("sucursal_asignada", "sucursal_asignada__pais").all()
        }

        allowed_paises = _user_allowed_paises_ids(request.user)

        data = []
        for u in admins:
            pa = perfiles.get(u.id)
            sucursal = getattr(pa, "sucursal_asignada", None)

            # Filtro por país: si no es superuser y tiene alcance por país,
            # solo mostrar admins cuya sucursal_asignada pertenezca a esos países.
            if allowed_paises is not None:
                # Si no hay sucursal asignada o el país no está permitido, se oculta
                if not sucursal or not sucursal.pais_id or sucursal.pais_id not in allowed_paises:
                    continue

            data.append(
                {
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "is_active": u.is_active,
                    "sucursal": getattr(sucursal, "nombre", None),
                    "perfil_activo": getattr(pa, "activo", None),
                }
            )

        return render(request, self.template_name, {"admins": data})


class ChainAdminAdminsCreateView(ChainOwnerRequiredMixin, View):
    template_name = "reservas/chainadmin/admin_form.html"

    def get(self, request):
        form = BranchAdminCreateForm()
        # Intentar limitar choices de sucursal según país (si el form tiene ese campo)
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

        # Si el que intenta togglear es ChainOwner País, solo puede togglear
        # admins cuya sucursal_asignada pertenezca a sus países permitidos.
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
