# ihop_system/scripts/diagnose_scope.py
from django.apps import apps

def describe_model(app_label, model_name):
    try:
        M = apps.get_model(app_label, model_name)
    except LookupError:
        print(f"❌ No existe {app_label}.{model_name}")
        return None
    print(f"\n✅ Modelo encontrado: {app_label}.{model_name}")
    print("Campos:")
    for f in M._meta.get_fields():
        print(f" - {f.name} ({f.__class__.__name__})")
    print(f"Total registros: {M.objects.count()}")
    return M

# Intenta ambos enfoques de alcance
CAS = describe_model("reservas", "CountryAdminScope")
PA  = describe_model("reservas", "PerfilAdmin")

# Si existe CAS, muestra 5 filas de ejemplo
if CAS:
    print("\nEjemplos CountryAdminScope:")
    for obj in CAS.objects.select_related().all()[:5]:
        print(
            "  ->",
            {f.name: getattr(obj, f.name, None) for f in CAS._meta.fields}
        )

# Si existe PerfilAdmin, intenta adivinar el M2M
if PA:
    cand = ["paises", "countries"]
    ok = None
    for c in cand:
        if hasattr(PA, c):
            ok = c
            break
    if ok:
        print(f"\nPerfilAdmin M2M detectado: .{ok}")
        for p in PA.objects.select_related("user").all()[:5]:
            try:
                nombres = list(getattr(p, ok).values_list("nombre", flat=True))
            except Exception:
                nombres = ["<error al leer>"]
            print(f"  -> {p.user} :: {nombres}")
    else:
        print("\n⚠️ PerfilAdmin existe pero no se halló M2M 'paises' ni 'countries'.")
