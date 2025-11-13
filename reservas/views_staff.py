# reservas/views_staff.py
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from .models import Sucursal, Mesa
from .forms import WalkInReservaForm
from django.utils.decorators import method_decorator
from django.contrib.admin.views.decorators import staff_member_required
from django.views.generic import ListView


def _staff_perm(user):
    return user.is_authenticated and user.is_staff

def _resolver_sucursal(request, form=None):
    """
    Determina la sucursal 'actual' para filtrar mesas.
    Orden:
      1) form.data['sucursal'] o form.initial['sucursal']
      2) ?sucursal=ID en la URL
      3) request.sucursal (si la pones en middleware)
      4) atributo user.sucursal_asignada (si lo usas)
      5) primera sucursal visible para el usuario
    """
    # 1) del form
    if form:
        sid = (form.data.get("sucursal")
               or (form.initial.get("sucursal") if hasattr(form, "initial") else None))
        if sid:
            try:
                return Sucursal.objects.get(pk=sid)
            except Sucursal.DoesNotExist:
                pass

    # 2) por GET
    sid = request.GET.get("sucursal")
    if sid:
        try:
            return Sucursal.objects.get(pk=sid)
        except Sucursal.DoesNotExist:
            pass

    # 3) atributo en request (si lo manejas)
    if hasattr(request, "sucursal") and isinstance(request.sucursal, Sucursal):
        return request.sucursal

    # 4) atributo en user (si lo tienes)
    suc = getattr(request.user, "sucursal_asignada", None)
    if isinstance(suc, Sucursal):
        return suc

    # 5) fallback: primera sucursal que el user puede ver
    # (ajústalo si tienes un manager for_user())
    return Sucursal.objects.order_by("nombre").first()

@login_required
@user_passes_test(_staff_perm)
def admin_walkin_reserva(request):
    """
    Formulario rápido de reserva (Walk-in).
    Filtra el select de mesas según la sucursal resuelta.
    """
    if request.method == "POST":
        form = WalkinForm(request.POST)
    else:
        form = WalkinForm()

    sucursal_actual = _resolver_sucursal(request, form)

    # IMPORTANTÍSIMO: filtrar las mesas por sucursal para que el select NO esté vacío
    if sucursal_actual:
        form.fields["mesa"].queryset = (
            Mesa.objects.filter(sucursal=sucursal_actual, activa=True)
            .order_by("numero", "id")
        )
        # si el campo sucursal está visible, preselecciona
        if "sucursal" in form.fields and not form.fields["sucursal"].widget.is_hidden:
            form.fields["sucursal"].initial = sucursal_actual.id
    else:
        form.fields["mesa"].queryset = Mesa.objects.none()

    if request.method == "POST" and form.is_valid():
        reserva = form.save()
        messages.success(request, _("Reserva creada correctamente."))
        return redirect("reservas:admin_dashboard")

    return render(request, "reservas/admin_walkin_form.html", {"form": form})


# Si tienes un mixin propio para filtrar por permisos/país, lo usamos.
# Si no existe, creamos un fallback inofensivo que lista todo.
try:
    from .mixins import VisibleSucursalQuerysetMixin  # tu mixin, si existe
except Exception:
    class VisibleSucursalQuerysetMixin:
        def get_queryset(self):
            return Sucursal.objects.all()

@method_decorator(staff_member_required, name="dispatch")
class StaffSucursalesListView(VisibleSucursalQuerysetMixin, ListView):
    model = Sucursal
    template_name = "reservas/chainadmin/sucursales_list.html"
    context_object_name = "sucursales"

    def get_queryset(self):
        # Heredamos del mixin si lo hay; si no, usamos el fallback
        base = super().get_queryset() if hasattr(super(), "get_queryset") else Sucursal.objects.all()
        return base.select_related("pais").order_by("pais__nombre", "nombre")
