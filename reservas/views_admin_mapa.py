from django.shortcuts import get_object_or_404, render
from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.views import View
from django.urls import reverse
from django.utils.safestring import mark_safe
import json

from .models import Sucursal, Mesa
from .permissions import assert_user_can_manage_sucursal


@method_decorator(staff_member_required, name="dispatch")
class AdminMapaSucursalView(View):
    # IMPORTANTE: la ruta del template debe incluir la carpeta "reservas/"
    template_name = "reservas/admin_mapa_sucursal.html"

    def get(self, request, sucursal_id):
        # Seguridad: sólo sucursales visibles para el usuario
        sucursal = get_object_or_404(Sucursal.objects.for_user(request.user), pk=sucursal_id)
        assert_user_can_manage_sucursal(request.user, sucursal)

        # Query de mesas (orden opcional, para consistencia)
        mesas_qs = Mesa.objects.filter(sucursal=sucursal).order_by("id")

        # Compatibilidad con tu template actual que itera "estado_mesas"
        estado_mesas = [
            {"mesa": m, "estado": "DISPONIBLE", "reservas": []}
            for m in mesas_qs
        ]

        # Datos crudos para el JS (y por si algún bloque usa "mesas" / "mesas_initial")
        mesas_values = list(
            mesas_qs.values(
                "id", "numero", "zona", "pos_x", "pos_y", "capacidad", "estado", "bloqueada"
            )
        )

        ctx = {
            "sucursal": sucursal,

            # Compat con el template que ya tienes:
            "estado_mesas": estado_mesas,

            # También los paso como listas simples por si los usas:
            "mesas": mesas_values,
            "mesas_initial": mesas_values,

            # JSON listo para tu JS (sin escapar)
            "mesas_json": mark_safe(json.dumps(mesas_values)),

            # Endpoints para el front
            "api_list_url": reverse("reservas:api_list_mesas", args=[sucursal.id]),
            "api_save_url": reverse("reservas:api_guardar_posiciones", args=[sucursal.id]),
        }
        return render(request, self.template_name, ctx)
