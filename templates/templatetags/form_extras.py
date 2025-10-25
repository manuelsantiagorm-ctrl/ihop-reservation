from django import template
register = template.Library()

@register.filter
def addclass(field, css):
    return field.as_widget(attrs={**field.field.widget.attrs, "class": css})

@register.filter
def attr(field, args):
    # uso: {{ field|attr:"placeholder,IHOP CDMX" }}
    key, value = args.split(",", 1)
    return field.as_widget(attrs={**field.field.widget.attrs, key.strip(): value.strip()})
