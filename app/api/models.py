from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.conf import settings
from cloudinary_storage.storage import RawMediaCloudinaryStorage


# ---------------------------------------------------------------------------
# USER
# ---------------------------------------------------------------------------

class CustomUserManager(BaseUserManager):
    def create_user(self, email, full_name, password=None, role='staff', **extra_fields):
        if not email:
            raise ValueError('Users must have an email address.')
        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, role=role, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, full_name, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, full_name, password, role='admin', **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('staff', 'Staff Member'),
        ('admin', 'Administrator'),
    )

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='staff')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.email}) - {self.role}"

    @property
    def initials(self):
        parts = self.full_name.split()
        return ''.join(p[0].upper() for p in parts[:2]) if parts else self.email[0].upper()


# ---------------------------------------------------------------------------
# TASKS  (internal to-dos — separate from client Bookings)
# ---------------------------------------------------------------------------

class Task(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('overdue', 'Overdue'),
        ('complete', 'Complete'),
    )

    PRIORITY_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    )

    title = models.CharField(max_length=255)
    tag = models.CharField(max_length=50, blank=True)  # e.g. Backend, Security, UI/UX
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_tasks'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='medium')
    # Set by an assignee (staff) to flag "I believe this is done" without letting them
    # change status directly — an admin still has to confirm via PATCH status=complete.
    completion_requested = models.BooleanField(default=False)
    due_date = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, related_name='created_tasks'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# ACTIVITY LOG  (drives the "Team Efficiency Feed")
# ---------------------------------------------------------------------------

class ActivityLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activities'
    )
    action = models.CharField(max_length=255)  # e.g. "completed 5 tasks", "flagged blocker on X"
    related_task = models.ForeignKey(
        Task, on_delete=models.SET_NULL, null=True, blank=True, related_name='activities'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Per-user read tracking — needed because the same activity entries can be
    # viewed by multiple admins independently (each has their own read state),
    # so a single boolean on the model wouldn't work.
    read_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='read_activity_logs', blank=True
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.full_name}: {self.action}"


# ---------------------------------------------------------------------------
# BOOKINGS  (client self-scheduling)
# ---------------------------------------------------------------------------

class Booking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    )

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings'
    )
    service_name = models.CharField(max_length=255)
    scheduled_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_at']

    def __str__(self):
        return f"{self.service_name} - {self.client.full_name} ({self.scheduled_at:%Y-%m-%d %H:%M})"


# ---------------------------------------------------------------------------
# DOCUMENTS  (Cloudinary uploads)
# ---------------------------------------------------------------------------

class Document(models.Model):
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='documents'
    )
    # Lets an admin share a document directly into a specific staff member's
    # view, separate from who actually uploaded it — mirrors Task.assignee.
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='assigned_documents'
    )
    title = models.CharField(max_length=255)
    category = models.CharField(max_length=100, blank=True)  # e.g. Architecture Guides, Security Protocols
    file = models.FileField(upload_to='documents/', storage=RawMediaCloudinaryStorage())
    file_size_mb = models.FloatField(null=True, blank=True)
    audit_notice = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-uploaded_at']

    def save(self, *args, **kwargs):
        if self.file and not self.file_size_mb:
            try:
                self.file_size_mb = round(self.file.size / (1024 * 1024), 2)
            except Exception:
                pass
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


# ---------------------------------------------------------------------------
# INVOICES
# ---------------------------------------------------------------------------

class Invoice(models.Model):
    STATUS_CHOICES = (
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
    )

    client = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='invoices'
    )
    booking = models.ForeignKey(
        Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='invoices'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice #{self.id} - {self.client.full_name} (${self.amount})"


# ---------------------------------------------------------------------------
# PLATFORM SETTINGS  (single row — global ops config, admin-editable)
# ---------------------------------------------------------------------------

class PlatformSettings(models.Model):
    ENV_CHOICES = (
        ('prod', 'Production (Live Webhooks)'),
        ('staging', 'Staging Canary'),
        ('dev', 'Development Sandbox'),
    )

    workspace_title = models.CharField(max_length=255, default='OpsPortal Enterprise')
    environment_stage = models.CharField(max_length=20, choices=ENV_CHOICES, default='prod')
    fallback_api_url = models.URLField(blank=True, default='')

    email_alerts_enabled = models.BooleanField(default=True)
    slack_webhooks_enabled = models.BooleanField(default=False)
    mfa_enforced = models.BooleanField(default=True)

    # Set only by the rotate-secret endpoint — never directly editable.
    secret_key_rotated_at = models.DateTimeField(null=True, blank=True)

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+'
    )

    class Meta:
        verbose_name = 'Platform Settings'
        verbose_name_plural = 'Platform Settings'

    def __str__(self):
        return 'Platform Settings'

    # Enforced as a true singleton: always load/update row pk=1, creating it
    # with defaults on first access rather than requiring a fixture or a
    # manual admin step before the Settings page can load.
    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)