# imports habituales
from django.shortcuts import render
from django.utils import timezone
from .models import Sucursal

def seleccionar_sucursal(request):
    """
    Vista existente: aquí solo añadimos 'sucursales_carrusel' al contexto
    para mostrar el carrusel arriba de los resultados.
    """
    # --- tu lógica existente para date/time/party/q/results ---
    date = request.GET.get("date") or timezone.localdate().strftime("%Y-%m-%d")
    time = request.GET.get("time") or timezone.localtime().strftime("%H:%M")
    party = request.GET.get("party") or "2"
    q = (request.GET.get("q") or "").strip()

    # ... aquí mantén tu búsqueda y la paginación ...
    # results = [...]

    # === NUEVO: dataset para el carrusel ===
    sucursales_carrusel = (
        Sucursal.objects.filter(activa=True)
        .order_by("-rating", "nombre")[:12]
    )

    ctx = {
        # lo que ya tenías:
        "date": date,
        "time": time,
        "party": party,
        "q": q,
        "results": results,               # ya lo traes en tu código
        "page_obj": page_obj,             # idem
        # nuevo:
        "sucursales_carrusel": sucursales_carrusel,
        "party_range": range(1, 13),
    }
    return render(request, "reservas/seleccionar_sucursal.html", ctx)
