# -*- coding: utf-8 -*-
from django.views.generic import TemplateView
from django.utils.timezone import now
from datetime import timedelta
from django.db.models import Count, Avg
from reservas.models import Reserva, Sucursal
from reservas.mixins import ChainScopeMixin  # si ya tienes algo similar
from django.contrib.auth.mixins import LoginRequiredMixin

class CountryAdminDashboardView(LoginRequiredMixin, ChainScopeMixin, TemplateView):
    template_name = "reservas/chainadmin_dashboard_country.html"

    # Ajusta este método para devolver un queryset de sucursales filtrado por países del usuario
    def visible_sucursales_qs(self):
        # Si ya tienes un mixin que filtra por países, úsalo. Si no:
        user = self.request.user
        # Ejemplo: asumiendo user.perfiladmin.countries (M2M o lista de códigos)
        countries = getattr(getattr(user, "perfiladmin", None), "countries", None)
        qs = Sucursal.objects.all()
        if countries:
            qs = qs.filter(pais__in=countries)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        suc_qs = self.visible_sucursales_qs()
        reservas_qs = Reserva.objects.filter(sucursal__in=suc_qs)

        today = now().date()
        start = today - timedelta(days=13)

        # Series por día (últimos 14 días)
        per_day = (
            reservas_qs
            .filter(local_service_date__range=(start, today))
            .values("local_service_date")
            .annotate(total=Count("id"), avg_size=Avg("personas"))
            .order_by("local_service_date")
        )

        labels = []
        totals = []
        avg_sizes = []
        totals_30 = reservas_qs.filter(local_service_date__gte=today - timedelta(days=30)).count()
        totals_today = reservas_qs.filter(local_service_date=today).count()
        totals_month = reservas_qs.filter(local_service_date__gte=today.replace(day=1)).count()

        for d in range(14):
            day = start + timedelta(days=d)
            labels.append(day.strftime("%d %b"))
            rec = next((x for x in per_day if x["local_service_date"] == day), None)
            if rec:
                totals.append(rec["total"])
                avg_sizes.append(float(rec["avg_size"] or 0))
            else:
                totals.append(0)
                avg_sizes.append(0)

        ctx.update({
            "labels": labels,
            "totals": totals,
            "avg_sizes": avg_sizes,
            "totals_30": totals_30,
            "totals_today": totals_today,
            "totals_month": totals_month,
            "suc_count": suc_qs.count(),
        })
        return ctx
