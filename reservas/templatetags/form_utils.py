from django import template

register = template.Library()

def _parse_kv_list(value: str) -> dict:
    attrs = {}
    if not value:
        return attrs
    for pair in value.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            attrs[k.strip()] = v.strip()
    return attrs

@register.filter
def attrs(field, value: str):
    """
    Aplica múltiples atributos al widget en una sola pasada.
    Soporta:
      - class=...      (sobrescribe clases)
      - class+=...     (agrega clases sin borrar las existentes)
    Uso:
      {{ form.email|attrs:"class+=form-control,autocomplete=email,placeholder=tu@email.com" }}
    """
    widget_attrs = field.field.widget.attrs.copy()
    extras = _parse_kv_list(value)

    # merge inteligente para class+=
    if "class+" in extras:
        prev = widget_attrs.get("class", "")
        widget_attrs["class"] = (prev + " " + extras.pop("class+")).strip()

    # el resto se sobreescribe normal
    widget_attrs.update(extras)
    return field.as_widget(attrs=widget_attrs)
