"""
URL configuration for ihop_system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    # Admin de Django
    path('admin/', admin.site.urls),

    # Autenticación (login/logout con templates de registration/)
    path('accounts/', include('django.contrib.auth.urls')),

    # Incluye las URLs de la app "reservas" con namespace "reservas"
    path('', include(('reservas.urls', 'reservas'), namespace='reservas')),
]
#urlpatterns = [
 #   path('', include('reservas.urls')),
  #  path('admin/', admin.site.urls),
   # path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    #path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    #path('register/', reservas_views.register, name='register'),
    #path('reservar/<int:mesa_id>/', reservas_views.reservar, name='reservar'),
    #path('cancelar/<int:reserva_id>/', reservas_views.cancelar_reserva, name='cancelar_reserva'),  # <-- ¡Agrega esta aquí!
    #path('', reservas_views.home, name='home'),
    #path('mis_reservas/', reservas_views.mis_reservas, name='mis_reservas'),
    #path('seleccionar_sucursal/', reservas_views.seleccionar_sucursal, name='seleccionar_sucursal'),
    #path('mesas/<int:sucursal_id>/', reservas_views.ver_mesas, name='ver_mesas'),
    

#]
