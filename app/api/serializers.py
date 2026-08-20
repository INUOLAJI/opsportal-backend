import os
from rest_framework import serializers
from .models import User, Task, ActivityLog, Booking, Document, Invoice, PlatformSettings
from .tokens import send_verification_email

# Max allowed upload size: 10MB
MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.png', '.jpg', '.jpeg', '.txt', '.csv', '.xlsx']


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    company_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    company_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    company_address = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = ['email', 'full_name', 'password', 'role', 'company_name', 'company_phone', 'company_address']

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_role(self, value):
        if value not in ['staff', 'admin']:
            raise serializers.ValidationError("Invalid role specified.")
        return value

    def create(self, validated_data):
        company_name = validated_data.pop('company_name', None)
        company_phone = validated_data.pop('company_phone', '')
        company_address = validated_data.pop('company_address', '')
        role = validated_data.get('role', 'staff')

        request = self.context.get('request')
        company = None

        if request and request.user and request.user.is_authenticated:
            # If created by an authenticated user (e.g. Admin creating Staff), assign to Admin's exact company
            company = request.user.get_or_create_company()
        elif role == 'admin':
            # Admin registering a new company -> create a fresh, dedicated Company instance
            c_name = company_name.strip() if company_name else f"{validated_data.get('full_name')}'s Enterprise"
            from .models import Company
            company = Company.objects.create(
                name=c_name,
                phone=company_phone,
                address=company_address
            )
        else:
            from .models import Company
            c_name = company_name.strip() if company_name else f"{validated_data.get('full_name')}'s Workspace"
            company = Company.objects.create(name=c_name)

        raw_password = validated_data.get('password')
        user = User.objects.create_user(company=company, **validated_data)

        if role == 'staff':
            user.is_verified = False
            user.save(update_fields=['is_verified'])
            # Pass the raw password through while we still have it — it's
            # hashed the moment create_user() saves the model, so this is
            # the only point it's available for the invite email.
            send_verification_email(user, temp_password=raw_password)
        return user


class UserSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.name', read_only=True)
    company_id = serializers.IntegerField(source='company.id', read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'role', 'company', 'company_id', 'company_name', 'is_active', 'is_verified', 'date_joined']
        read_only_fields = ['id', 'company', 'company_id', 'company_name', 'date_joined']


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

    def validate_assignee(self, value):
        if value:
            request = self.context.get('request')
            if request and request.user and request.user.is_authenticated:
                user_company = request.user.company or request.user.get_or_create_company()
                if value.company_id != user_company.id:
                    raise serializers.ValidationError("Assignee must belong to your company.")
        return value


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

    def validate_assigned_to(self, value):
        if value:
            request = self.context.get('request')
            if request and request.user and request.user.is_authenticated:
                user_company = request.user.company or request.user.get_or_create_company()
                if value.company_id != user_company.id:
                    raise serializers.ValidationError("Assigned member must belong to your company.")
        return value

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
    company_name = serializers.SerializerMethodField()
    company_phone = serializers.SerializerMethodField()
    company_address = serializers.SerializerMethodField()
    admin_name = serializers.SerializerMethodField()
    admin_email = serializers.SerializerMethodField()
    admin_role = serializers.SerializerMethodField()

    class Meta:
        model = PlatformSettings
        fields = [
            'workspace_title', 'environment_stage', 'fallback_api_url',
            'email_alerts_enabled', 'slack_webhooks_enabled', 'mfa_enforced',
            'company_name', 'company_phone', 'company_address',
            'admin_name', 'admin_email', 'admin_role',
            'secret_key_rotated_at', 'updated_at', 'updated_by', 'updated_by_name',
        ]
        read_only_fields = ['secret_key_rotated_at', 'updated_at', 'updated_by', 'admin_name', 'admin_email', 'admin_role']

    def get_company_name(self, obj):
        if obj.company and obj.company.name:
            return obj.company.name
        request = self.context.get('request')
        if request and request.user and request.user.company and request.user.company.name:
            return request.user.company.name
        return ''

    def get_company_phone(self, obj):
        if obj.company and obj.company.phone:
            return obj.company.phone
        request = self.context.get('request')
        if request and request.user and request.user.company and request.user.company.phone:
            return request.user.company.phone
        return ''

    def get_company_address(self, obj):
        if obj.company and obj.company.address:
            return obj.company.address
        request = self.context.get('request')
        if request and request.user and request.user.company and request.user.company.address:
            return request.user.company.address
        return ''

    def get_admin_name(self, obj):
        request = self.context.get('request')
        return request.user.full_name if request and request.user and request.user.is_authenticated else ''

    def get_admin_email(self, obj):
        request = self.context.get('request')
        return request.user.email if request and request.user and request.user.is_authenticated else ''

    def get_admin_role(self, obj):
        request = self.context.get('request')
        return request.user.role if request and request.user and request.user.is_authenticated else ''

    def update(self, instance, validated_data):
        company_name = self.initial_data.get('company_name')
        company_phone = self.initial_data.get('company_phone')
        company_address = self.initial_data.get('company_address')

        instance = super().update(instance, validated_data)

        request = self.context.get('request')
        company = instance.company or (request.user.get_or_create_company() if request and request.user else None)

        if company:
            if company_name is not None and str(company_name).strip():
                company.name = str(company_name).strip()
            if company_phone is not None:
                company.phone = str(company_phone).strip()
            if company_address is not None:
                company.address = str(company_address).strip()
            company.save()

            if not instance.company:
                instance.company = company
                instance.save(update_fields=['company'])

        return instance