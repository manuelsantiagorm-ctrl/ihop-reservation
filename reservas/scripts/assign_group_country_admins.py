# reservas/scripts/assign_group_country_admins.py
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group

COUNTRY_ADMIN_EMAILS = [
    "admin.sa@ihop.com","admin.ar@ihop.com","admin.bh@ihop.com","admin.ca@ihop.com",
    "admin.qa@ihop.com","admin.cl@ihop.com","admin.co@ihop.com","admin.ec@ihop.com",
    "admin.ae@ihop.com","admin.es@ihop.com","admin.us@ihop.com","admin.ph@ihop.com",
    "admin.gt@ihop.com","admin.kw@ihop.com","admin.mx@ihop.com","admin.pe@ihop.com",
]

def run():
    User = get_user_model()
    group = Group.objects.get(name="Country Admin")
    ok, faltan = 0, []
    for email in COUNTRY_ADMIN_EMAILS:
        try:
            u = User.objects.get(email=email)
        except User.DoesNotExist:
            try:
                u = User.objects.get(username=email)  # por si usas username=email
            except User.DoesNotExist:
                faltan.append(email)
                continue
        u.is_staff = True
        u.groups.add(group)
        u.save()
        ok += 1
        print(f"OK  {email}")
    if faltan:
        print("\nFALTAN usuarios (crea primero estos emails):")
        for e in faltan:
            print(f" - {e}")
    print(f"\nAsignados al grupo: {ok}")

if __name__ == "__main__":
    run()
