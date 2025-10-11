# reservas/views_api.py
from django.http import JsonResponse, HttpResponseBadRequest
from django.views import View
from django.utils.dateparse import parse_datetime
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from zoneinfo import ZoneInfo

from .models import Sucursal, Reserva, Cliente, Mesa
from .mixins import ChainScopeMixin

@method_decorator(csrf_exempt, name="dispatch")
class SucursalesJsonView(ChainScopeMixin, View):
    def get(self, request):
        qs = Sucursal.objects.filter(activo=True).select_related("pais")
        iso2 = request.GET.get("pais")
        if iso2:
            qs = qs.filter(pais__iso2=iso2.upper())
        qs = self.chain_scope(qs, "pais_id")
        data = [{
            "id": s.id,
            "nombre": s.nombre,
            "slug": s.slug,
            "pais": s.pais.iso2 if s.pais_id else None,
            "timezone": s.timezone,
            "lat": float(s.lat) if s.lat is not None else None,
            "lng": float(s.lng) if s.lng is not None else None,
            "direccion": s.direccion,
            "activo": s.activo,
        } for s in qs]
        return JsonResponse({"sucursales": data})

@method_decorator(csrf_exempt, name="dispatch")
class ReservaCreateFromLocalView(ChainScopeMixin, View):
    def post(self, request):
        import json
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except Exception:
            return HttpResponseBadRequest("JSON inválido")

        sucursal_id = payload.get("sucursal_id")
        mesa_id = payload.get("mesa_id")
        cliente_data = payload.get("cliente") or {}
        local_inicio_str = payload.get("local_inicio")
        dur = int(payload.get("dur_minutes") or 90)
        num = int(payload.get("num_personas") or 2)

        if not sucursal_id or not local_inicio_str:
            return HttpResponseBadRequest("Faltan sucursal_id o local_inicio")

        qs_suc = self.chain_scope(Sucursal.objects.all(), "pais_id")
        try:
            suc = qs_suc.get(pk=sucursal_id)
        except Sucursal.DoesNotExist:
            return HttpResponseBadRequest("Sucursal no encontrada o fuera de alcance")

        tzname = suc.timezone or "UTC"
        tz = ZoneInfo(tzname)

        local_inicio = parse_datetime(local_inicio_str)
        if local_inicio is None:
            return HttpResponseBadRequest("local_inicio inválido (ISO8601)")

        if local_inicio.tzinfo is not None:
            local_inicio = local_inicio.astimezone(tz)
        else:
            local_inicio = local_inicio.replace(tzinfo=tz)

        from django.db import transaction
        from datetime import timedelta
        with transaction.atomic():
            email = (cliente_data.get("email") or "").strip().lower()
            if email:
                cli, _ = Cliente.objects.get_or_create(
                    email=email,
                    defaults={"nombre": cliente_data.get("nombre") or email.split("@")[0],
                              "telefono": cliente_data.get("telefono") or ""},
                )
            else:
                cli = Cliente.objects.create(
                    nombre=cliente_data.get("nombre") or "Cliente",
                    email="",
                    telefono=cliente_data.get("telefono") or "",
                )

            mesa = None
            if mesa_id:
                try:
                    mesa = Mesa.objects.get(pk=mesa_id, sucursal=suc)
                except Mesa.DoesNotExist:
                    return HttpResponseBadRequest("Mesa no encontrada en esa sucursal")

            r = Reserva(cliente=cli, mesa=mesa, sucursal=suc, num_personas=num)

            # Si tienes helpers en el modelo, úsalos; si no, hazlo aquí:
            inicio_utc = local_inicio.astimezone(ZoneInfo("UTC"))
            r.inicio_utc = inicio_utc
            r.fin_utc = inicio_utc + timedelta(minutes=dur)
            r.local_inicio = local_inicio
            r.local_fin = local_inicio + timedelta(minutes=dur)
            r.local_service_date = local_inicio.date()

            # Compatibilidad con tu campo 'fecha'
            r.fecha = local_inicio

            r.save()

        return JsonResponse({
            "ok": True,
            "reserva": {
                "id": r.id,
                "folio": r.folio,
                "sucursal": suc.nombre,
                "timezone": tzname,
                "local_inicio": r.local_inicio.isoformat() if r.local_inicio else None,
                "inicio_utc": r.inicio_utc.isoformat() if r.inicio_utc else None,
            }
        }, status=201)
