from collections import defaultdict
from django.views import View
from django.shortcuts import render
from django.contrib.auth import get_user_model

from .utils_auth import user_allowed_countries
from .models import CountryAdminScope, Sucursal, PerfilAdmin, Pais

User = get_user_model()

def countries_for_user(user):
    """
    Países visibles para el usuario:
      - superuser: todos
      - Country Admin: via CountryAdminScope
      - Branch Admin: país de su sucursal_asignada (PerfilAdmin)
    """
    if getattr(user, "is_superuser", False):
        return Pais.objects.all()

    allowed = user_allowed_countries(user)  # QS de Pais por CountryAdminScope
    if allowed.exists():
        return allowed

    # Branch Admin → país de su sucursal asignada
    try:
        pa = PerfilAdmin.objects.select_related("sucursal_asignada__pais").get(user=user)
        if pa.sucursal_asignada and pa.sucursal_asignada.pais_id:
            return Pais.objects.filter(pk=pa.sucursal_asignada.pais_id)
    except PerfilAdmin.DoesNotExist:
        pass

    return Pais.objects.none()

# Detecta el modelo de reservas (si existe); si no, desactiva ese KPI.
try:
    from .models import Reserva as RESERVA_MODEL  # ajusta si tu modelo se llama distinto
except Exception:
    RESERVA_MODEL = None


class CountryAdminsAllView(View):
    """
    Referentes (admins de país) por pestaña + KPIs por país.
    - Superuser ve todo
    - Country Admin ve sus países (CountryAdminScope)
    - Branch Admin ve el país de su sucursal asignada
    """
    template_name = "reservas/chainadmin/country_admins_all.html"

    def get(self, request):
        visible_countries = countries_for_user(request.user).order_by("nombre")

        # Referentes por país (CountryAdminScope)
        scope_qs = (
            CountryAdminScope.objects
            .select_related("user", "pais")
            .filter(pais__in=visible_countries)
            .order_by("pais__nombre", "user__username")
        )
        users_by_country = defaultdict(list)
        for r in scope_qs:
            users_by_country[r.pais_id].append(r.user)

        # Para KPIs:
        sucursales_qs = Sucursal.objects.select_related("pais").filter(pais__in=visible_countries)
        branch_admins_qs = (
            User.objects.filter(is_staff=True, groups__name="BranchAdmin")
            .select_related("perfiladmin", "perfiladmin__sucursal_asignada", "perfiladmin__sucursal_asignada__pais")
            .distinct()
        )

        # Construir tabs listos para el template (sin diccionarios anidados raros)
        tabs = []
        for pais in visible_countries:
            suc_count = sucursales_qs.filter(pais=pais).count()
            ba_count = branch_admins_qs.filter(perfiladmin__sucursal_asignada__pais=pais).count()
            if RESERVA_MODEL is not None:
                try:
                    res_count = RESERVA_MODEL.objects.filter(sucursal__pais=pais).count()
                except Exception:
                    res_count = None
            else:
                res_count = None

            tabs.append({
                "pais": pais,                        # objeto Pais
                "users": users_by_country[pais.id],  # lista de referentes (User)
                "kpis": {
                    "sucursales": suc_count,
                    "branch_admins": ba_count,
                    "reservas": res_count,           # puede ser None si no hay modelo
                },
            })

        return render(request, self.template_name, {"tabs": tabs})
