from django.db import migrations
import uuid

def gen_slugs(apps, schema_editor):
    Sucursal = apps.get_model('reservas', 'Sucursal')
    # Rellena sólo los que no tengan slug
    for s in Sucursal.objects.filter(slug__isnull=True) | Sucursal.objects.filter(slug=''):
        s.slug = str(uuid.uuid4())
        s.save(update_fields=['slug'])

class Migration(migrations.Migration):

    dependencies = [
        ('reservas', '0011_remove_sucursal_total_mesas_sucursal_administradores_and_more'),
    ]

    operations = [
        migrations.RunPython(gen_slugs, migrations.RunPython.noop),
    ]
