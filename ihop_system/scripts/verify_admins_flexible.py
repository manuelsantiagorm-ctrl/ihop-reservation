# ihop_system/scripts/verify_admins_flexible.py
from django.apps import apps
from django.contrib.auth import get_user_model
from reservas.models import Pais

U = get_user_model()

ADMINS = [
    "admin.sa@ihop.com","admin.ar@ihop.com","admin.bh@ihop.com","admin.ca@ihop.com",
    "admin.qa@ihop.com","admin.cl@ihop.com","admin.co@ihop.com","admin.ec@ihop.com",
    "admin.ae@ihop.com","admin.es@ihop.com","admin.us@ihop.com","admin.ph@ihop.com",
    "admin.gt@ihop.com","admin.kw@ihop.com","admin.mx@ihop.com","admin.pe@ihop.com",
]

def detect_scope():
    """Devuelve (mode, Model, field) donde:
       mode='cas' -> CountryAdminScope con FK a Pais llamada `field`
       mode='perfil' -> PerfilAdmin con M2M a Pais llamada `field`
    """
    # 1) CountryAdminScope
    try:
        CAS = apps.get_model("reservas", "CountryAdminScope")
        fk_candidates = ["pais", "country", "país", "pais_fk", "country_fk"]
        for name in fk_candidates:
            try:
                f = CAS._meta.get_field(name)
                if getattr(getattr(f, "remote_field", None), "model", None) is Pais:
                    return ("cas", CAS, name)
            except Exception:
                pass
    except LookupError:
        CAS = None

    # 2) PerfilAdmin
    try:
        PA = apps.get_model("reservas", "PerfilAdmin")
        for name in ["paises", "countries"]:
            if hasattr(PA, name):
                return ("perfil", PA, name)
    except LookupError:
        PA = None

    return (None, None, None)

def paises_de_usuario(u):
    mode, M, field = detect_scope()
    if mode == "cas":
        # lee directo desde CAS (no por relación inversa)
        qs = M.objects.filter(user=u).select_related(field)
        nombres = []
        for obj in qs:
            p = getattr(obj, field, None)
            if p:
                nombres.append(p.nombre)
        return nombres
    elif mode == "perfil":
        try:
            perfil = M.objects.get(user=u)
        except M.DoesNotExist:
            return []
        return list(getattr(perfil, field).values_list("nombre", flat=True))
    return []

print("EMAIL                              | is_staff | Países asignados")
print("-"*90)
for email in ADMINS:
    try:
        u = U.objects.get(username=email)
        nombres = paises_de_usuario(u)
        print(f"{email:<34} | {str(u.is_staff):<7} | {', '.join(nombres) or '-'}")
    except U.DoesNotExist:
        print(f"{email:<34} | {'-':<7} | (no existe)")
