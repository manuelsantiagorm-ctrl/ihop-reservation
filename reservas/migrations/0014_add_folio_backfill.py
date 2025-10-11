# reservas/migrations/0014_add_folio_backfill.py
from django.db import migrations
import uuid

def generar_folio():
    return f"R-{uuid.uuid4().hex[:8].upper()}"

def forwards(apps, schema_editor):
    Reserva = apps.get_model('reservas', 'Reserva')
    usados = set(Reserva.objects.exclude(folio__isnull=True).values_list('folio', flat=True))
    for r in Reserva.objects.all():
        if not r.folio:
            f = generar_folio()
            while f in usados:
                f = generar_folio()
            r.folio = f
            r.save(update_fields=['folio'])
            usados.add(f)

def backwards(apps, schema_editor):
    Reserva = apps.get_model('reservas', 'Reserva')
    Reserva.objects.update(folio=None)

class Migration(migrations.Migration):

    dependencies = [
        ('reservas', '0013_reserva_folio_alter_sucursal_administradores_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
