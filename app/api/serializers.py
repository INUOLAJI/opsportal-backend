import os
from rest_framework import serializers
from .models import User, Task, ActivityLog, Booking, Document, Invoice, PlatformSettings

# Max allowed upload size: 10MB
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.txt', '.csv', '.xlsx']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['email', 'full_name', 'password', 'role']

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_role(self, value):
        if value not in ['staff', 'admin']:
            raise serializers.ValidationError("Invalid role specified.")
        return value

    def create(self, validated_data):
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'role', 'is_active', 'date_joined']
        read_only_fields = ['id', 'date_joined']


class TaskSerializer(serializers.ModelSerializer):
    assignee_name = serializers.CharField(source='assignee.full_name', read_only=True)
    assignee_initials = serializers.CharField(source='assignee.initials', read_only=True)

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'tag', 'assignee', 'assignee_name', 'assignee_initials',
            'status', 'priority', 'completion_requested', 'due_date', 'created_by', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at']


class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.full_name', read_only=True)
    user_initials = serializers.CharField(source='user.initials', read_only=True)
    is_read = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = ['id', 'user', 'user_name', 'user_initials', 'action', 'related_task', 'created_at', 'is_read']
        read_only_fields = ['user', 'created_at']

    def get_is_read(self, obj):
        request = self.context.get('request')
        # Freshly-created activities broadcast over WebSocket are serialized
        # without a request in context — treat those as unread by default,
        # which is correct since nobody has seen them yet.
        if not request or not request.user or not request.user.is_authenticated:
            return False
        return obj.read_by.filter(pk=request.user.pk).exists()


class BookingSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.full_name', read_only=True)

    class Meta:
        model = Booking
        fields = [
            'id', 'client', 'client_name', 'service_name', 'scheduled_at',
            'status', 'notes', 'created_at', 'updated_at'
        ]
        read_only_fields = ['client', 'created_at', 'updated_at']


class DocumentSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.CharField(source='uploaded_by.full_name', read_only=True)
    assigned_to_name = serializers.CharField(source='assigned_to.full_name', read_only=True)
    assigned_to_initials = serializers.CharField(source='assigned_to.initials', read_only=True)

    class Meta:
        model = Document
        fields = [
            'id', 'uploaded_by', 'uploaded_by_name', 'assigned_to', 'assigned_to_name',
            'assigned_to_initials', 'title', 'category', 'file',
            'file_size_mb', 'audit_notice', 'uploaded_at', 'updated_at'
        ]
        read_only_fields = ['uploaded_by', 'file_size_mb', 'uploaded_at', 'updated_at']

    def validate_file(self, value):
        if value.size > MAX_UPLOAD_SIZE_BYTES:
            raise serializers.ValidationError("File size exceeds maximum allowable limit of 10MB.")

        ext = os.path.splitext(value.name)[1].lower()
        if ext not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise serializers.ValidationError(f"File extension '{ext}' is not permitted.")

        return value


class InvoiceSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.full_name', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'client', 'client_name', 'booking', 'amount',
            'status', 'due_date', 'created_at', 'updated_at'
        ]
        read_only_fields = ['client', 'created_at', 'updated_at']


class PlatformSettingsSerializer(serializers.ModelSerializer):
    updated_by_name = serializers.CharField(source='updated_by.full_name', read_only=True)

    class Meta:
        model = PlatformSettings
        fields = [
            'workspace_title', 'environment_stage', 'fallback_api_url',
            'email_alerts_enabled', 'slack_webhooks_enabled', 'mfa_enforced',
            'secret_key_rotated_at', 'updated_at', 'updated_by', 'updated_by_name',
        ]
        read_only_fields = ['secret_key_rotated_at', 'updated_at', 'updated_by']