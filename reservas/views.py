from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils.timezone import now
from datetime import timedelta

from .models import Cliente, Sucursal, Mesa, Reserva, PerfilAdmin

from .forms import ClienteRegistrationForm, ReservaForm

# ========================
# PANEL DE CONTROL 
# ========================
@login_required
def panel_mesas(request):
    if request.user.is_superuser:
        mesas = Mesa.objects.all()
    else:
        try:
            perfil = PerfilAdmin.objects.get(user=request.user)
            mesas = Mesa.objects.filter(sucursal=perfil.sucursal)
        except PerfilAdmin.DoesNotExist:
            mesas = []
    return render(request, 'reservas/panel_mesas.html', {'mesas': mesas})


# ========================
# VISTA DE INICIO (HOME)
# ========================
@login_required
def home(request):
    if request.user.is_authenticated and hasattr(request.user, 'cliente'):
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
            return redirect('home')
    else:
        form = ClienteRegistrationForm()
    return render(request, 'reservas/register.html', {'form': form})


# ========================
# HACER UNA RESERVACIÓN
# ========================
@login_required
def reservar(request, mesa_id):
    cliente = get_object_or_404(Cliente, user=request.user)
    mesa = get_object_or_404(Mesa, id=mesa_id)

    if request.method == 'POST':
        form = ReservaForm(request.POST, mesa=mesa, cliente=cliente)
        if form.is_valid():
            reserva = form.save(commit=False)
            reserva.cliente = cliente
            reserva.mesa = mesa
            reserva.estado = 'PEND'
            reserva.save()

            messages.success(request, '✅ Reservación realizada con éxito.')
            return redirect('mis_reservas')
        else:
            messages.error(request, '❌ Revisa los campos del formulario.')
    else:
        form = ReservaForm(mesa=mesa, cliente=cliente)

    return render(request, 'reservas/reservar.html', {
        'form': form,
        'mesa': mesa
    })


# ========================
# CANCELAR UNA RESERVA
# ========================
@login_required
def cancelar_reserva(request, reserva_id):
    reserva = get_object_or_404(Reserva, id=reserva_id)

    if reserva.cliente.user != request.user:
        return HttpResponseForbidden("No tienes permiso para cancelar esta reservación.")

    reserva.estado = 'CANC'
    reserva.save()
    return redirect('mis_reservas')


# ========================
# ADMINISTRADOR: VER RESERVAS
# ========================
# @login_required
# def admin_reservas(request):
 #    try:
   #      admin = Administrador.objects.get(user=request.user)
    # except Administrador.DoesNotExist:
      #   return HttpResponseForbidden("No tienes permisos para ver esta sección.")

#     reservas = Reserva.objects.filter(
   #      mesa__sucursal__in=admin.sucursales.all()
    # ).order_by('-fecha')

    # return render(request, 'reservas/admin_reservas.html', {'reservas': reservas})


# ========================
# ADMINISTRADOR: CONFIRMAR RESERVA
# ========================
# @login_required
# def confirmar_reserva(request, reserva_id):
 #    reserva = get_object_or_404(Reserva, id=reserva_id)

   #  try:
     #    admin = Administrador.objects.get(user=request.user)
       #  if reserva.mesa.sucursal not in admin.sucursales.all():
         #    return HttpResponseForbidden("No puedes confirmar esta reservación.")
    # except Administrador.DoesNotExist:
      #   return HttpResponseForbidden("No eres administrador.")

    # reserva.estado = 'CONF'
    # reserva.save()
    # return redirect('admin_reservas')


# ========================
# CLIENTE: VER MIS RESERVAS
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
def seleccionar_sucursal(request):
    sucursales = Sucursal.objects.all()
    return render(request, 'reservas/seleccionar_sucursal.html', {'sucursales': sucursales})


def ver_mesas(request, sucursal_id):
    sucursal = get_object_or_404(Sucursal, id=sucursal_id)
    mesas = Mesa.objects.filter(sucursal=sucursal)
    return render(request, 'reservas/ver_mesas.html', {
        'sucursal': sucursal,
        'mesas': mesas
    })
