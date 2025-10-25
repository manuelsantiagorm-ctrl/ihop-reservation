# ihop_system/scripts/assign_scope_flexible.py
from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import transaction
from reservas.models import Pais

U = get_user_model()

ADMINS = [
    ("admin.sa@ihop.com", "SA"),
    ("admin.ar@ihop.com", "AR"),
    ("admin.bh@ihop.com", "BH"),
    ("admin.ca@ihop.com", "CA"),
    ("admin.qa@ihop.com", "QA"),
    ("admin.cl@ihop.com", "CL"),
    ("admin.co@ihop.com", "CO"),
    ("admin.ec@ihop.com", "EC"),
    ("admin.ae@ihop.com", "AE"),
    ("admin.es@ihop.com", "ES"),
    ("admin.us@ihop.com", "US"),
    ("admin.ph@ihop.com", "PH"),
    ("admin.gt@ihop.com", "GT"),
    ("admin.kw@ihop.com", "KW"),
    ("admin.mx@ihop.com", "MX"),
    ("admin.pe@ihop.com", "PE"),
]

def get_scope_model_and_field():
    """Devuelve (Modelo, nombre_fk_a_Pais) ó (None, None) si no hay CAS;
       si no, intenta PerfilAdmin + nombre_m2m ('paises'/'countries')."""
    # 1) CountryAdminScope
    try:
        CAS = apps.get_model("reservas", "CountryAdminScope")
        # detecta el campo FK a Pais probando nombres comunes
        fk_candidates = ["pais", "country", "país", "pais_fk", "country_fk"]
        for name in fk_candidates:
            try:
                f = CAS._meta.get_field(name)
                # verifica que apunte a Pais
                if getattr(getattr(f, "remote_field", None), "model", None) is Pais:
                    return ("cas", CAS, name)
            except Exception:
                pass
    except LookupError:
        CAS = None

    # 2) PerfilAdmin M2M
    try:
        PA = apps.get_model("reservas", "PerfilAdmin")
        m2m_candidates = ["paises", "countries"]
        for name in m2m_candidates:
            if hasattr(PA, name):
                return ("perfil", PA, name)
    except LookupError:
        PA = None

    return (None, None, None)

def assign_to_user(user, pais):
    mode, M, field = get_scope_model_and_field()
    if mode is None:
        raise RuntimeError("No encontré ni CountryAdminScope ni PerfilAdmin con M2M a País.")

    if not user.is_staff:
        user.is_staff = True
        user.save(update_fields=["is_staff"])

    if mode == "cas":
        # get_or_create con campo dinámico
        kwargs = {"user": user, field: pais}
        M.objects.get_or_create(**kwargs)
        return f"CAS: {field}={pais.iso2}"
    else:
        # PerfilAdmin M2M
        perfil, _ = M.objects.get_or_create(user=user)
        getattr(perfil, field).add(pais)
        return f"PerfilAdmin: add {field}={pais.iso2}"

@transaction.atomic
def run():
    for email, iso2 in ADMINS:
        try:
            user = U.objects.get(username=email)
        except U.DoesNotExist:
            print(f"❌ Usuario no existe: {email}")
            continue
        try:
            pais = Pais.objects.get(iso2=iso2)
        except Pais.DoesNotExist:
            print(f"❌ País ISO2 no existe: {iso2} para {email}")
            continue
        how = assign_to_user(user, pais)
        print(f"✔ {email} → {pais.nombre} ({how})")

    print("\n🎯 Listo. Vuelve a correr verify_admins.py para confirmar.")

if __name__ == "__main__":
    run()
