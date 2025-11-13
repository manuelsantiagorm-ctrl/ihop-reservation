# reservas/views_chainadmin_menu.py
from django.contrib.auth.decorators import login_required, user_passes_test
from django.utils.decorators import method_decorator
from django.views.generic import ListView, CreateView, UpdateView
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.http import JsonResponse
from django.db.models import Q
from django.contrib import messages
from django.utils.translation import gettext_lazy as _

from .models_menu import CatalogCategory, CatalogItem, CatalogComboComponent
from .forms_menu import CategoryForm, MenuItemForm, ComboComponentForm

def _chainadmin_perm(user):
    return user.is_superuser or user.has_perm("reservas.manage_branches")

@method_decorator([login_required, user_passes_test(_chainadmin_perm)], name="dispatch")
class MenuCatalogListView(ListView):
    template_name = "reservas/chainadmin/menu_catalogo.html"
    model = CatalogItem
    context_object_name = "items"
    paginate_by = 30
    def get_queryset(self):
        q = (self.request.GET.get("q") or "").strip()
        cat = (self.request.GET.get("cat") or "").strip()
        qs = CatalogItem.objects.select_related("categoria").all()
        if q:
            qs = qs.filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
        if cat:
            qs = qs.filter(categoria_id=cat)
        return qs.order_by("categoria__orden", "nombre")
    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["categorias"] = CatalogCategory.objects.filter(activo=True).order_by("orden", "nombre")
        ctx["q"] = self.request.GET.get("q", "")
        ctx["cat"] = self.request.GET.get("cat", "")
        return ctx

@method_decorator([login_required, user_passes_test(_chainadmin_perm)], name="dispatch")
class CategoryCreateView(CreateView):
    template_name = "reservas/chainadmin/menu_category_form.html"
    form_class = CategoryForm
    success_url = reverse_lazy("reservas:chainadmin_menu_catalogo")

@method_decorator([login_required, user_passes_test(_chainadmin_perm)], name="dispatch")
class CategoryUpdateView(UpdateView):
    template_name = "reservas/chainadmin/menu_category_form.html"
    form_class = CategoryForm
    model = CatalogCategory
    success_url = reverse_lazy("reservas:chainadmin_menu_catalogo")

@method_decorator([login_required, user_passes_test(_chainadmin_perm)], name="dispatch")
class MenuItemCreateView(CreateView):
    template_name = "reservas/chainadmin/menu_item_form.html"
    form_class = MenuItemForm
    success_url = reverse_lazy("reservas:chainadmin_menu_catalogo")

@method_decorator([login_required, user_passes_test(_chainadmin_perm)], name="dispatch")
class MenuItemUpdateView(UpdateView):
    template_name = "reservas/chainadmin/menu_item_form.html"
    form_class = MenuItemForm
    model = CatalogItem
    success_url = reverse_lazy("reservas:chainadmin_menu_catalogo")

@login_required
@user_passes_test(_chainadmin_perm)
def combo_edit_components(request, pk):
    combo = CatalogItem.objects.filter(pk=pk, es_combo=True).select_related("categoria").first()
    if not combo:
        messages.error(request, _("Combo no encontrado"))
        return redirect("reservas:chainadmin_menu_catalogo")
    if request.method == "POST":
        form = ComboComponentForm(request.POST)
        if form.is_valid():
            comp = form.save(commit=False)
            comp.combo = combo
            try:
                comp.save()
                messages.success(request, _("Componente agregado."))
            except Exception as e:
                messages.error(request, _("No se pudo agregar: ") + str(e))
        else:
            messages.error(request, _("Formulario inválido."))
        return redirect("reservas:chainadmin_menu_combo", pk=combo.pk)
    componentes = combo.componentes.select_related("item").all()
    form = ComboComponentForm()
    return render(request, "reservas/chainadmin/menu_combo_form.html", {
        "combo": combo, "componentes": componentes, "form": form
    })

@login_required
@user_passes_test(_chainadmin_perm)
def combo_delete_component(request, pk, comp_id):
    combo = CatalogItem.objects.filter(pk=pk, es_combo=True).first()
    if not combo:
        messages.error(request, _("Combo no encontrado"))
        return redirect("reservas:chainadmin_menu_catalogo")
    CatalogComboComponent.objects.filter(pk=comp_id, combo=combo).delete()
    messages.success(request, _("Componente eliminado."))
    return redirect("reservas:chainadmin_menu_combo", pk=combo.pk)

@login_required
@user_passes_test(_chainadmin_perm)
def menuitem_toggle_active(request, pk):
    item = CatalogItem.objects.filter(pk=pk).first()
    if not item:
        messages.error(request, _("Ítem no encontrado"))
    else:
        item.activo = not item.activo
        item.save(update_fields=["activo"])
        messages.success(request, _("Estado actualizado."))
    return redirect("reservas:chainadmin_menu_catalogo")



@login_required
@user_passes_test(_chainadmin_perm)
def api_buscar_items(request):
    q = (request.GET.get("q") or "").strip()
    if not q:
        return JsonResponse({"results": []})
    qs = (CatalogItem.objects
          .filter(activo=True)
          .filter(Q(codigo__icontains=q) | Q(nombre__icontains=q))
          .select_related("categoria")
          .order_by("categoria__orden", "nombre")[:30])
    return JsonResponse({
        "results": [{
            "id": i.id,
            "codigo": i.codigo,
            "nombre": i.nombre,
            "precio": float(i.precio_combo if (i.es_combo and i.precio_combo is not None) else i.precio),
            "es_combo": i.es_combo,
            "categoria": i.categoria.nombre,
        } for i in qs]
    })
