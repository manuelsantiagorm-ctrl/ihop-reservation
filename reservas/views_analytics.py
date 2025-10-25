# reservas/views_analytics.py
from datetime import date
from django.utils import timezone
from django.views import View
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model

from django.db.models import Count, Avg, Q, F
from django.db.models.functions import TruncDay, TruncMonth, TruncYear, ExtractHour

from .models import Pais, Sucursal, PerfilAdmin
from .utils_auth import user_allowed_countries

User = get_user_model()

# ===========================
#  Config del modelo/fields
# ===========================
from .models import Reserva as RESERVA_MODEL
RESERVA_DATE_FIELD = "fecha"          # campo datetime de tu modelo
RESERVA_PARTY_FIELD = "num_personas"  # tamaño de grupo en tu modelo


# ===========================
#  Helpers de scoping país
# ===========================
def countries_for_user(user):
    """
    Devuelve QS de países que el usuario puede ver.
    - Superuser: todos.
    - CountryAdminScope (via user_allowed_countries).
    - Branch admin: país de su sucursal asignada.
    """
    if getattr(user, "is_superuser", False):
        return Pais.objects.all()

    allowed = user_allowed_countries(user)
    if allowed.exists():
        return allowed

    try:
        pa = PerfilAdmin.objects.select_related("sucursal_asignada__pais").get(user=user)
        if pa.sucursal_asignada and pa.sucursal_asignada.pais_id:
            return Pais.objects.filter(pk=pa.sucursal_asignada.pais_id)
    except PerfilAdmin.DoesNotExist:
        pass

    return Pais.objects.none()


# ===========================
#  Página del dashboard
# ===========================
class AnalyticsPageView(LoginRequiredMixin, View):
    template_name = "reservas/analytics/country_dashboard.html"

    def get(self, request):
        # Países permitidos para el usuario
        if request.user.is_superuser:
            allowed = Pais.objects.all().order_by("nombre")
        else:
            allowed = user_allowed_countries(request.user).order_by("nombre")

        default_country_id = allowed.first().id if allowed.exists() else None

        # Defaults de filtros (el JS los respeta si vienen)
        default_from = date.today().replace(day=1)   # primer día del mes actual
        default_to = ""                               # vacío → el JS lo tomará como hoy
        default_granularity = "day"

        return render(request, self.template_name, {
            "allowed_countries": allowed,
            "default_country_id": default_country_id,
            "default_from": default_from.isoformat(),
            "default_to": default_to,
            "default_granularity": default_granularity,
        })


# ===========================
#  API: Datos del dashboard
# ===========================
class AnalyticsDataView(LoginRequiredMixin, View):
    """
    GET /chainadmin/analytics/data/?pais=<id>&from=YYYY-MM-DD&to=YYYY-MM-DD&g=day|month|year
    Responde JSON con:
      - kpis: total_reservas, sucursales, branch_admins
      - time_series: labels[], values[]
      - peak_hours: 24 bins (0..23)
      - party_size: bins {"1","2","3","4","5+"}
      - top_branches: [{"name","count"} ...]
    """
    def get(self, request):
        # Validación país y scoping
        try:
            pais_id = int(request.GET.get("pais"))
        except Exception:
            return HttpResponseBadRequest("pais requerido")

        allowed_ids = set(countries_for_user(request.user).values_list("id", flat=True))
        if pais_id not in allowed_ids:
            return HttpResponseBadRequest("pais no autorizado")

        # Fechas (local → aware)
        today = timezone.localdate()
        date_from_str = request.GET.get("from") or today.isoformat()
        date_to_str = request.GET.get("to") or today.isoformat()
        try:
            date_from = timezone.datetime.fromisoformat(date_from_str).date()
            date_to = timezone.datetime.fromisoformat(date_to_str).date()
        except Exception:
            return HttpResponseBadRequest("formato de fecha inválido")

        if date_to < date_from:
            date_to = date_from

        tz = timezone.get_current_timezone()
        dt_from = timezone.make_aware(
            timezone.datetime.combine(date_from, timezone.datetime.min.time()), tz
        )
        dt_to = timezone.make_aware(
            timezone.datetime.combine(date_to, timezone.datetime.max.time()), tz
        )

        # Granularidad
        gran = (request.GET.get("g") or "day").lower()
        if gran not in {"day", "month", "year"}:
            gran = "day"

        # Base queryset (país + rango)
        date_field = F(RESERVA_DATE_FIELD)
        base = (RESERVA_MODEL.objects
                .filter(sucursal__pais_id=pais_id)
                .filter(**{f"{RESERVA_DATE_FIELD}__gte": dt_from,
                           f"{RESERVA_DATE_FIELD}__lte": dt_to}))

        # KPIs
        total_reservas = base.count()
        sucursales = Sucursal.objects.filter(pais_id=pais_id).count()
        branch_admins = (User.objects.filter(
            is_staff=True,
            groups__name="BranchAdmin",
            perfiladmin__sucursal_asignada__pais_id=pais_id
        ).distinct().count())

        # Serie temporal
        if gran == "day":
            grouped = base.annotate(g=TruncDay(date_field))
            order_fmt = "%d %b %Y"
        elif gran == "month":
            grouped = base.annotate(g=TruncMonth(date_field))
            order_fmt = "%b %Y"
        else:
            grouped = base.annotate(g=TruncYear(date_field))
            order_fmt = "%Y"

        series_qs = grouped.values("g").annotate(c=Count("id")).order_by("g")
        labels, values = [], []
        for row in series_qs:
            g = row["g"]
            try:
                lbl = (g.date().strftime(order_fmt) if hasattr(g, "date") else g.strftime(order_fmt))
            except Exception:
                lbl = str(g)
            labels.append(lbl)
            values.append(row["c"])

        # Horas pico (0..23)
        hours_qs = (base
                    .annotate(h=ExtractHour(date_field))
                    .values("h")
                    .annotate(c=Count("id"))
                    .order_by("h"))
        peak_hours = [0] * 24
        for row in hours_qs:
            h = row["h"]
            if isinstance(h, int) and 0 <= h <= 23:
                peak_hours[h] = row["c"]

        # Party size
        bins = {"1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
        if RESERVA_PARTY_FIELD:
            party_qs = base.values(RESERVA_PARTY_FIELD).annotate(c=Count("id"))
            for row in party_qs:
                p = int(row[RESERVA_PARTY_FIELD] or 0)
                if p <= 1:
                    bins["1"] += row["c"]
                elif p == 2:
                    bins["2"] += row["c"]
                elif p == 3:
                    bins["3"] += row["c"]
                elif p == 4:
                    bins["4"] += row["c"]
                else:
                    bins["5+"] += row["c"]

        # Top sucursales
        top_qs = (base.values(name=F("sucursal__nombre"))
                       .annotate(count=Count("id"))
                       .order_by("-count")[:10])
        top_branches = list(top_qs)

        return JsonResponse({
            "kpis": {
                "total_reservas": total_reservas,
                "sucursales": sucursales,
                "branch_admins": branch_admins,
            },
            "time_series": {"labels": labels, "values": values, "granularity": gran},
            "peak_hours": peak_hours,
            "party_size": bins,
            "top_branches": top_branches,
        })


# ===============================
#   API: Sucursales por país
#   /chainadmin/analytics/sucursales/?pais=<id>
# ===============================
class BranchesForCountryView(LoginRequiredMixin, View):
    def get(self, request):
        try:
            pais_id = int(request.GET.get("pais"))
        except Exception:
            return HttpResponseBadRequest("pais requerido")

        allowed_ids = set(countries_for_user(request.user).values_list("id", flat=True))
        if pais_id not in allowed_ids:
            return HttpResponseBadRequest("pais no autorizado")

        qs = Sucursal.objects.filter(pais_id=pais_id).order_by("nombre")
        data = [{"id": s.id, "nombre": s.nombre, "slug": s.slug} for s in qs]
        return JsonResponse({"branches": data})


# ===============================
#   API: Comparar sucursales
#   /chainadmin/analytics/compare/?pais=..&from=YYYY-MM-DD&to=YYYY-MM-DD
#     &sucursales=1,2,3&h_from=8&h_to=22&cap_min=1&cap_max=12&estados=CONF,PEND
# ===============================
class AnalyticsCompareView(LoginRequiredMixin, View):
    def get(self, request):
        # Validación país
        try:
            pais_id = int(request.GET.get("pais"))
        except Exception:
            return HttpResponseBadRequest("pais requerido")

        allowed_ids = set(countries_for_user(request.user).values_list("id", flat=True))
        if pais_id not in allowed_ids:
            return HttpResponseBadRequest("pais no autorizado")

        # Rango de fechas (local → aware)
        try:
            dfrom = request.GET.get("from") or timezone.localdate().isoformat()
            dto   = request.GET.get("to")   or timezone.localdate().isoformat()
            date_from = timezone.datetime.fromisoformat(dfrom).date()
            date_to   = timezone.datetime.fromisoformat(dto).date()
        except Exception:
            return HttpResponseBadRequest("formato de fecha inválido")

        if date_to < date_from:
            date_to = date_from

        tz = timezone.get_current_timezone()
        dt_from = timezone.make_aware(
            timezone.datetime.combine(date_from, timezone.datetime.min.time()), tz
        )
        dt_to = timezone.make_aware(
            timezone.datetime.combine(date_to, timezone.datetime.max.time()), tz
        )

        # Base queryset por país + rango
        date_field = F(RESERVA_DATE_FIELD)
        base = (RESERVA_MODEL.objects
                .filter(sucursal__pais_id=pais_id)
                .filter(**{f"{RESERVA_DATE_FIELD}__gte": dt_from,
                           f"{RESERVA_DATE_FIELD}__lte": dt_to}))

        # Filtro por sucursales específicas (ids separados por coma)
        suc_ids_raw = (request.GET.get("sucursales") or "").strip()
        if suc_ids_raw:
            suc_ids = [int(x) for x in suc_ids_raw.split(",") if x.strip().isdigit()]
            if suc_ids:
                base = base.filter(sucursal_id__in=suc_ids)

        # Filtro por horas (0..23) basado en hora del campo fecha
        h_from = request.GET.get("h_from")
        h_to   = request.GET.get("h_to")
        if h_from or h_to:
            base = base.annotate(hora=ExtractHour(date_field))
            if h_from not in (None, ""):
                try:
                    base = base.filter(hora__gte=int(h_from))
                except Exception:
                    pass
            if h_to not in (None, ""):
                try:
                    base = base.filter(hora__lte=int(h_to))
                except Exception:
                    pass

        # Filtro por capacidad de mesa
        cap_min = request.GET.get("cap_min")
        cap_max = request.GET.get("cap_max")
        if cap_min:
            try:
                base = base.filter(mesa__capacidad__gte=int(cap_min))
            except Exception:
                pass
        if cap_max:
            try:
                base = base.filter(mesa__capacidad__lte=int(cap_max))
            except Exception:
                pass

        # Filtro por estados
        estados_raw = (request.GET.get("estados") or "").strip()
        if estados_raw:
            estados = [e.strip().upper() for e in estados_raw.split(",") if e.strip()]
            base = base.filter(estado__in=estados)

        # Agregaciones por sucursal
        grouped = (base
            .values("sucursal_id", "sucursal__nombre")
            .annotate(
                total=Count("id"),
                conf=Count("id", filter=Q(estado="CONF")),
                canc=Count("id", filter=Q(estado="CANC")),
                nosh=Count("id", filter=Q(estado="NOSH")),
                pend=Count("id", filter=Q(estado="PEND")),
                avg_pax=Avg(RESERVA_PARTY_FIELD),
                mesas=Count("mesa", distinct=True),
            )
            .order_by("-total"))

        rows = []
        for r in grouped:
            total = r["total"] or 0

            def pct(x):
                return (100.0 * (x or 0) / total) if total else 0.0

            rows.append({
                "sucursal": f'{r["sucursal_id"]} — {r["sucursal__nombre"]}',
                "total": total,
                "conf": r["conf"] or 0,
                "conf_pct": pct(r["conf"]),
                "canc": r["canc"] or 0,
                "canc_pct": pct(r["canc"]),
                "nosh": r["nosh"] or 0,
                "nosh_pct": pct(r["nosh"]),
                "pend": r["pend"] or 0,
                "avg_pax": float(r["avg_pax"] or 0.0),
                "mesas": r["mesas"] or 0,
            })

        return JsonResponse({"rows": rows})
