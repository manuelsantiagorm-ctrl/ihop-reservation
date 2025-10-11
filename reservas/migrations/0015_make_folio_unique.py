from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('reservas', '0014_add_folio_backfill'),
    ]

    operations = [
        migrations.AlterField(
            model_name='reserva',
            name='folio',
            field=models.CharField(max_length=10, unique=True, db_index=True),
        ),
    ]
