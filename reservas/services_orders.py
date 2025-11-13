from .models_orders import Order, OrderStatus

def liberar_preorden_al_checkin(reserva):
    """
    Llama esta función desde tu vista/acción de check-in.
    - Busca orden DRAFT ligada a la reserva y la manda a SUBMITTED.
    """
    qs = Order.objects.filter(reserva=reserva, status=OrderStatus.DRAFT)
    for o in qs:
        o.submit_to_kitchen()
    return qs.count()
