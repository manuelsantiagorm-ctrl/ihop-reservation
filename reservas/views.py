from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.contrib.admin.views.decorators import staff_member_required
from datetime import timedelta

from .models import Cliente, Sucursal, Mesa, Reserva, PerfilAdmin
from .forms import ClienteRegistrationForm, ReservaForm
from .utils import conflicto_y_disponible


# ========================
# ADMIN: CONFIRMAR RESERVA
# ========================
@staff_member_required
def confirmar_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva, pk=reserva_id)
    if reserva.estado != 'CONF':
        reserva.estado = 'CONF'
        reserva.save(update_fields=['estado'])
        messages.success(request, "Reservación confirmada correctamente.")
    else:
        messages.info(request, "La reservación ya estaba confirmada.")
    return redirect('reservas:admin_reservas')


# ========================
# PANEL DE MESAS
# ========================
@login_required
def panel_mesas(request):
    if request.user.is_superuser:
        mesas = Mesa.objects.all()
    else:
        try:
            perfil = request.user.perfiladmin
            mesas = Mesa.objects.filter(sucursal=perfil.sucursal_asignada)
        except PerfilAdmin.DoesNotExist:
            mesas = []
    return render(request, 'reservas/panel_mesas.html', {'mesas': mesas})


# ========================
# HOME
# ========================
@login_required
def home(request):
    if hasattr(request.user, 'cliente'):
        cliente = request.user.cliente
        sucursales_recomendadas = Sucursal.objects.filter(codigo_postal=cliente.codigo_postal)
        otras_sucursales = Sucursal.objects.exclude(codigo_postal=cliente.codigo_postal)
    else:
        sucursales_recomendadas = []
        otras_sucursales = Sucursal.objects.all()

    return render(request, 'reservas/home.html', {
        'sucursales_recomendadas': sucursales_recomendadas,
        'otras_sucursales': otras_sucursales
    })


# ========================
# REGISTRO DE CLIENTE
# ========================
def register(request):
    if request.method == 'POST':
        form = ClienteRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('reservas:home')
    else:
        form = ClienteRegistrationForm()
    return render(request, 'reservas/register.html', {'form': form})


# ========================
# HACER UNA RESERVA (con bloqueo 70 min)
# ========================
@login_required
def reservar(request, mesa_id):
    cliente = get_object_or_404(Cliente, user=request.user)
    mesa = get_object_or_404(Mesa, id=mesa_id)

    if request.method == 'POST':
        form = ReservaForm(request.POST, mesa=mesa, cliente=cliente)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Bloqueo pesimista para evitar dobles reservas simultáneas
                    Mesa.objects.select_for_update().get(pk=mesa.pk)

                    fecha = form.cleaned_data['fecha']

                    # Revisa conflictos usando utils
                    conflicto, hora_disp = conflicto_y_disponible(mesa, fecha)

                    if conflicto:
                        messages.error(
                            request,
                            f"⚠ Lo sentimos, la mesa está ocupada hasta las {hora_disp.strftime('%H:%M')}."
                        )
                        return redirect('reservas:reservar', mesa_id=mesa.id)

                    # Guardar la reservación
                    reserva = form.save(commit=False)
                    reserva.cliente = cliente
                    reserva.mesa = mesa
                    reserva.estado = 'PEND'
                    reserva.full_clean()
                    reserva.save()

                messages.success(request, '✅ Reservación realizada con éxito.')
                return redirect('reservas:mis_reservas')

            except Exception as e:
                messages.error(request, f'❌ No se pudo completar la reservación: {e}')
        else:
            messages.error(request, '❌ Revisa los campos del formulario.')
    else:
        form = ReservaForm(mesa=mesa, cliente=cliente)

    return render(request, 'reservas/reservar.html', {
        'form': form,
        'mesa': mesa
    })


# ========================
# CANCELAR RESERVA
# ========================
@login_required
def cancelar_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id)
    if reserva.cliente.user != request.user:
        return HttpResponseForbidden("No tienes permiso para cancelar esta reservación.")
    reserva.estado = 'CANC'
    reserva.save(update_fields=['estado'])
    messages.success(request, "Reservación cancelada.")
    return redirect('reservas:mis_reservas')


# ========================
# MIS RESERVAS
# ========================
@login_required
def mis_reservas(request):
    cliente = request.user.cliente
    activa = Reserva.objects.filter(cliente=cliente, estado='PEND').order_by('-fecha').first()
    pasadas = Reserva.objects.filter(cliente=cliente).exclude(id=getattr(activa, 'id', None)).order_by('-fecha')[:2]
    return render(request, 'reservas/mis_reservas.html', {
        'reserva_activa': activa,
        'reservas_pasadas': pasadas
    })


# ========================
# SUCURSAL Y MESAS
# ========================
@login_required
def seleccionar_sucursal(request):
    sucursales = Sucursal.objects.all()
    return render(request, 'reservas/seleccionar_sucursal.html', {'sucursales': sucursales})


@login_required
def ver_mesas(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, id=sucursal_id)
    mesas = Mesa.objects.filter(sucursal=sucursal)
    return render(request, 'reservas/ver_mesas.html', {'sucursal': sucursal, 'mesas': mesas})


# ========================
# ADMIN: LISTA DE RESERVAS
# ========================
@staff_member_required
def admin_reservas(request):
    if request.user.is_superuser:
        reservaciones = Reserva.objects.all().order_by('-fecha')
    else:
        try:
            perfil = request.user.perfiladmin
            reservaciones = Reserva.objects.filter(mesa__sucursal=perfil.sucursal_asignada).order_by('-fecha')
        except PerfilAdmin.DoesNotExist:
            reservaciones = Reserva.objects.none()
    return render(request, 'reservas/admin_reservas.html', {'reservaciones': reservaciones})
