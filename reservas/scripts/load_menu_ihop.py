# reservas/scripts/load_menu_ihop.py
from decimal import Decimal
from django.db import transaction, IntegrityError

# Modelos (soporta si los moviste a models_menu)
try:
    from reservas.models import CatalogCategory, CatalogItem, CatalogComboComponent
except Exception:
    from reservas.models_menu import CatalogCategory, CatalogItem, CatalogComboComponent

# Intentamos importar una Sucursal por si el item la requiere
try:
    from reservas.models import Sucursal  # tu modelo real de sucursal
except Exception:
    Sucursal = None


def _category_fk_name():
    for f in CatalogItem._meta.fields:
        if getattr(f, "remote_field", None) and f.remote_field and f.remote_field.model == CatalogCategory:
            return f.name
    return "category"


def _sucursal_fk_name():
    """Devuelve el nombre del campo FK a Sucursal si existe (sucursal, branch, tienda...)."""
    if not Sucursal:
        return None
    for f in CatalogItem._meta.fields:
        if getattr(f, "remote_field", None) and f.remote_field and f.remote_field.model == Sucursal:
            return f.name
    return None


CAT_FK = _category_fk_name()
SUC_FK = _sucursal_fk_name()

# Elige una sucursal por defecto si hace falta
DEFAULT_SUCURSAL = None
if SUC_FK:
    try:
        DEFAULT_SUCURSAL = Sucursal.objects.order_by("id").first()
    except Exception:
        DEFAULT_SUCURSAL = None


def cat(nombre, activo=True):
    obj, _ = CatalogCategory.objects.update_or_create(
        nombre=nombre, defaults={"activo": activo}
    )
    return obj


def _item_lookup_kwargs(codigo, suc=None):
    """Clave de búsqueda: (sucursal, codigo) si existe SUC_FK, si no solo codigo."""
    if SUC_FK and suc:
        return {SUC_FK: suc, "codigo": codigo}
    return {"codigo": codigo}


def item(categoria, codigo, nombre, precio, descripcion="", activo=True, suc=None, **extras):
    if SUC_FK and suc is None:
        suc = DEFAULT_SUCURSAL
    defaults = {
        CAT_FK: categoria,
        "nombre": nombre,
        "descripcion": descripcion,
        "precio": Decimal(str(precio)),
        "activo": activo,
    }
    if SUC_FK:
        defaults[SUC_FK] = suc

    # Copia extras si existen en tu modelo (impuesto, sku, is_combo, tipo, etc.)
    for k, v in extras.items():
        if hasattr(CatalogItem, k):
            defaults[k] = v

    obj, _ = CatalogItem.objects.update_or_create(
        **_item_lookup_kwargs(codigo, suc=suc),
        defaults=defaults,
    )
    return obj


def set_combo_flag(obj, value=True):
    for fld in ("is_combo", "es_combo", "tipo"):
        if hasattr(obj, fld):
            setattr(obj, fld, ("COMBO" if fld == "tipo" else value))
            obj.save(update_fields=[fld])


def ccmp(combo, it, qty=1):
    CatalogComboComponent.objects.update_or_create(
        combo=combo, item=it, defaults={"cantidad": qty}
    )


@transaction.atomic
def run():
    try:
        # 1) Categorías
        C_BEB = cat("Bebidas")
        C_PAN = cat("World Famous Pancakes")
        C_DES = cat("Desayunos")
        C_OME = cat("Omelettes")
        C_WAF = cat("Waffles & French Toast")
        C_ENT = cat("Entradas")
        C_SAN = cat("Sandwiches")
        C_BUR = cat("Hamburguesas")
        C_SID = cat("Sides")

        # 2) Bebidas (muestra)
        DR_CAFE     = item(C_BEB, "DR-CAF", "Café americano", 39)
        DR_CAPPU    = item(C_BEB, "DR-CAP", "Cappuccino", 65)
        DR_CHOC     = item(C_BEB, "DR-CHO", "Chocolate caliente", 59)
        DR_JUG_NAR  = item(C_BEB, "DR-JUG-NAR", "Jugo de naranja", 52)
        DR_JUG_MAN  = item(C_BEB, "DR-JUG-MAN", "Jugo Mighty Mango", 59)
        DR_REF_COC  = item(C_BEB, "DR-REF-COC", "Refresco Coca-Cola", 45)
        DR_REF_REF  = item(C_BEB, "DR-REF-REF", "Refresco Refill", 55)
        DR_MAL_VAN  = item(C_BEB, "DR-MAL-VAN", "Malteada vainilla", 89)
        DR_MAL_FRA  = item(C_BEB, "DR-MAL-FRA", "Malteada fresa", 89)

        # 3) Pancakes
        PAN_ORIG    = item(C_PAN, "PAN-ORIG", "Original Buttermilk (5 pzs)", 109)
        PAN_DBL_BLU = item(C_PAN, "PAN-DBLBLU", "Double Blueberry", 139)
        PAN_STRAW   = item(C_PAN, "PAN-STRAW", "Strawberry Banana", 139)
        PAN_NYCH    = item(C_PAN, "PAN-NYCH", "New York Cheesecake", 149)

        # 4) Desayunos / Omelettes / Waffles
        DES_2X2X2   = item(C_DES, "DES-2X2X2", "2x2x2 (2 hotcakes, 2 huevos, 2 tocinos)", 139)
        DES_SMOKE   = item(C_DES, "DES-SMOKE", "Smokehouse Combo", 189)
        OME_CHK_FAJ = item(C_OME, "OME-CHKFAJ", "Chicken Fajita Omelette", 199)
        OME_BACON   = item(C_OME, "OME-BACON", "Bacon Temptation Omelette", 199)
        WAF_CHKWAF  = item(C_WAF, "WAF-CHKWAF", "Chicken & Waffles", 189)
        WAF_BELG    = item(C_WAF, "WAF-BELG", "Belgian Waffle", 109)
        FT_ORIG     = item(C_WAF, "FT-ORIG", "Original French Toast", 119)

        # 5) Entradas / Sandwiches / Hamburguesas / Sides
        ENT_MOZZ    = item(C_ENT, "ENT-MOZZ", "Cheese Sticks", 129)
        ENT_ONRING  = item(C_ENT, "ENT-ONR", "Onion Rings", 99)
        SAN_CRN     = item(C_SAN, "SAN-CRN", "Spicy Chicken Ranch Sandwich", 179)
        SAN_CLUB    = item(C_SAN, "SAN-CLUB", "Original Chicken Club Sandwich", 179)
        BUR_PHILLY  = item(C_BUR, "BUR-PHLY", "Philly Cheese Steak Burger", 189)
        BUR_COWBOY  = item(C_BUR, "BUR-COW", "Cowboy BBQ Burger", 199)
        SIDE_PAPAS  = item(C_SID, "SIDE-PAP", "Papas a la francesa", 59)
        SIDE_HASH   = item(C_SID, "SIDE-HH", "Hash Browns", 49)
        SIDE_TOC    = item(C_SID, "SIDE-TOC", "Tocino (2 pzs)", 39)

        # 6) Combos (5)
        COM_1 = item(C_DES, "COMBO-CLAS-CAF", "Desayuno clásico + Café", 169, "2x2x2 + café")
        set_combo_flag(COM_1);  ccmp(COM_1, DES_2X2X2, 1);  ccmp(COM_1, DR_CAFE, 1)

        COM_2 = item(C_PAN, "COMBO-PAN-CAF", "Buttermilk Pancakes + Café", 139, "Pancakes + café")
        set_combo_flag(COM_2);  ccmp(COM_2, PAN_ORIG, 1);   ccmp(COM_2, DR_CAFE, 1)

        COM_3 = item(C_WAF, "COMBO-CHKWAF-REF", "Chicken & Waffles + Refresco", 219, "Chicken & Waffles + refresco")
        set_combo_flag(COM_3);  ccmp(COM_3, WAF_CHKWAF, 1); ccmp(COM_3, DR_REF_COC, 1)

        COM_4 = item(C_BUR, "COMBO-BUR-PAP-REF", "Hamburguesa + Papas + Refill", 229, "Burger + papas + refill")
        set_combo_flag(COM_4);  ccmp(COM_4, BUR_PHILLY, 1); ccmp(COM_4, SIDE_PAPAS, 1); ccmp(COM_4, DR_REF_REF, 1)

        COM_5 = item(C_DES, "COMBO-OME-JUG", "Omelette + Jugo", 229, "Omelette + jugo")
        set_combo_flag(COM_5);  ccmp(COM_5, OME_BACON, 1);  ccmp(COM_5, DR_JUG_NAR, 1)

    except Exception as e:
        # cualquier error revierte atomic y lo mostramos
        print("❌ Error cargando menú:", repr(e))
        raise

    print("✅ Catálogo base cargado/actualizado.")
    print(
        "Categorias:", CatalogCategory.objects.count(),
        "| Items:", CatalogItem.objects.count(),
        "| Componentes de combo:", CatalogComboComponent.objects.count()
    )


if __name__ == "__main__":
    run()
