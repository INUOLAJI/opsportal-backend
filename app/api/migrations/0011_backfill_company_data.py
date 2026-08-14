from django.db import migrations


def backfill_company_data(apps, schema_editor):
    Company = apps.get_model('api', 'Company')
    User = apps.get_model('api', 'User')
    Task = apps.get_model('api', 'Task')
    ActivityLog = apps.get_model('api', 'ActivityLog')
    Booking = apps.get_model('api', 'Booking')
    Document = apps.get_model('api', 'Document')
    Invoice = apps.get_model('api', 'Invoice')
    PlatformSettings = apps.get_model('api', 'PlatformSettings')

    # Step 1: Ensure at least one default company exists
    default_company, _ = Company.objects.get_or_create(
        name="OpsPortal Enterprise"
    )

    # Step 2: Assign users without a company to default_company
    for user in User.objects.filter(company__isnull=True):
        user.company = default_company
        user.save(update_fields=['company'])

    # Step 3: Backfill Task company
    for task in Task.objects.filter(company__isnull=True):
        comp = (task.created_by.company if task.created_by and task.created_by.company 
                else (task.assignee.company if task.assignee and task.assignee.company else default_company))
        task.company = comp
        task.save(update_fields=['company'])

    # Step 4: Backfill Document company
    for doc in Document.objects.filter(company__isnull=True):
        comp = (doc.uploaded_by.company if doc.uploaded_by and doc.uploaded_by.company 
                else (doc.assigned_to.company if doc.assigned_to and doc.assigned_to.company else default_company))
        doc.company = comp
        doc.save(update_fields=['company'])

    # Step 5: Backfill ActivityLog company
    for activity in ActivityLog.objects.filter(company__isnull=True):
        comp = activity.user.company if activity.user and activity.user.company else default_company
        activity.company = comp
        activity.save(update_fields=['company'])

    # Step 6: Backfill Booking company
    for booking in Booking.objects.filter(company__isnull=True):
        comp = booking.client.company if booking.client and booking.client.company else default_company
        booking.company = comp
        booking.save(update_fields=['company'])

    # Step 7: Backfill Invoice company
    for inv in Invoice.objects.filter(company__isnull=True):
        comp = inv.client.company if inv.client and inv.client.company else default_company
        inv.company = comp
        inv.save(update_fields=['company'])

    # Step 8: Backfill PlatformSettings company
    for ps in PlatformSettings.objects.filter(company__isnull=True):
        ps.company = default_company
        ps.save(update_fields=['company'])


def reverse_backfill(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0010_company_activitylog_company_booking_company_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_company_data, reverse_code=reverse_backfill),
    ]
