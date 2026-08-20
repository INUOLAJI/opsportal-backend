from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import cloudinary_storage.storage


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0011_backfill_company_data'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='assignees',
            field=models.ManyToManyField(
                blank=True,
                related_name='multi_assigned_tasks',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name='TaskAttachment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(
                    storage=cloudinary_storage.storage.RawMediaCloudinaryStorage(),
                    upload_to='task_attachments/',
                )),
                ('filename', models.CharField(blank=True, max_length=255)),
                ('file_size_mb', models.FloatField(blank=True, null=True)),
                ('uploaded_at', models.DateTimeField(auto_now_add=True)),
                ('task', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='attachments',
                    to='api.task',
                )),
                ('uploaded_by', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='task_attachments',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-uploaded_at'],
            },
        ),
    ]
