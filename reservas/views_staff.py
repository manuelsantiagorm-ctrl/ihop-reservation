from django.views.generic import ListView
from .models import Sucursal
from .mixins import VisibleSucursalQuerysetMixin  # o el mixin que estés usando

class StaffSucursalesListView(ListView):
    model = Sucursal
    template_name = "reservas/chainadmin/sucursales_list.html"
    context_object_name = "sucursales"

    def get_queryset(self):
        return (Sucursal.objects.for_user(self.request.user)
                .select_related("pais")
                .order_by("pais__nombre", "nombre"))
