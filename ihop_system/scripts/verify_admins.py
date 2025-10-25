# ihop_system/scripts/verify_admins.py
from django.contrib.auth import get_user_model
from reservas.models import Pais

U = get_user_model()

ADMINS = [
    "admin.sa@ihop.com","admin.ar@ihop.com","admin.bh@ihop.com","admin.ca@ihop.com",
    "admin.qa@ihop.com","admin.cl@ihop.com","admin.co@ihop.com","admin.ec@ihop.com",
    "admin.ae@ihop.com","admin.es@ihop.com","admin.us@ihop.com","admin.ph@ihop.com",
    "admin.gt@ihop.com","admin.kw@ihop.com","admin.mx@ihop.com","admin.pe@ihop.com",
]

def paises_de(u):
    # Detecta CountryAdminScope o PerfilAdmin.paises dinámicamente
    try:
        from reservas.models import CountryAdminScope
        return list(Pais.objects.filter(countryadminscope__user=u).values_list("nombre", flat=True))
    except Exception:
        try:
            from reservas.models import PerfilAdmin
            p = PerfilAdmin.objects.get(user=u)
            return list(p.paises.values_list("nombre", flat=True))
        except Exception:
            return []

print("EMAIL                              | is_staff | Países asignados")
print("-" * 90)
for email in ADMINS:
    try:
        u = U.objects.get(username=email)
        asignados = ", ".join(paises_de(u)) or "-"
        print(f"{email:<34} | {str(u.is_staff):<7} | {asignados}")
    except U.DoesNotExist:
        print(f"{email:<34} | {'-':<7} | (no existe)")
