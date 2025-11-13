from django.shortcuts import render, get_object_or_404
from django.contrib.admin.views.decorators import staff_member_required
from reservas.models import Mesa
from reservas.models_orders import Order

@staff_member_required
def crear_orden_mesa(request):
    mesa_id = request.GET.get("mesa_id")
    mesa = get_object_or_404(Mesa, id=mesa_id)
    sucursal = mesa.sucursal

    # Buscar si hay una orden abierta (status != CLOSED)
    orden, created = Order.objects.get_or_create(
        mesa=mesa,
        sucursal=sucursal,
        status__in=["DRAFT", "SUBMITTED", "IN_PREP"],
        defaults={"status": "DRAFT"}
    )

    context = {"mesa": mesa, "orden": orden}
    return render(request, "reservas/partials/orden_mesa.html", context)
