from rest_framework import status, generics, permissions, serializers
from django.contrib.auth import get_user_model, authenticate
from django.db import models
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Task, ActivityLog, Booking, Document, Invoice, PlatformSettings
from .serializers import (
    RegisterSerializer, UserSerializer, TaskSerializer, ActivityLogSerializer,
    BookingSerializer, DocumentSerializer, InvoiceSerializer, PlatformSettingsSerializer
)
from .permissions import IsOwnerOrAdmin, IsAdminUser
from .tokens import email_verification_token, send_verification_email

User = get_user_model()


def _is_admin(user):
    return bool(user.role == 'admin' or user.is_superuser)


def _staff_group(user_id):
    return f'staff_{user_id}_dashboard'


def _broadcast(group_name, event_type, payload_key, data):
    """Push a real-time event to a Channels group. No-ops quietly if the
    channel layer isn't configured, so this never breaks the HTTP response
    even if Redis/Channels is misconfigured."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    async_to_sync(channel_layer.group_send)(
        group_name, {"type": event_type, payload_key: data}
    )


def _broadcast_task(event_type, task):
    """Notify admins (always) and the assignee's personal group (if the
    assignee isn't an admin, since admins already get the admin broadcast)."""
    data = TaskSerializer(task).data
    _broadcast('admin_dashboard', event_type, 'task', data)
    if task.assignee_id and not _is_admin(task.assignee):
        _broadcast(_staff_group(task.assignee_id), event_type, 'task', data)


def _broadcast_activity(activity):
    data = ActivityLogSerializer(activity).data
    _broadcast('admin_dashboard', 'activity.created', 'activity', data)
    _broadcast(_staff_group(activity.user_id), 'activity.created', 'activity', data)


class AuthAnonRateThrottle(AnonRateThrottle):
    rate = '10/minute'


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

@extend_schema(
    request=RegisterSerializer,
    responses={201: OpenApiResponse(description='Account created successfully'), 400: OpenApiResponse(description='Validation error')},
)
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthAnonRateThrottle])
def register_user(request):
    serializer = RegisterSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        return Response(
            {
                "message": "Account created successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": user.role,
                }
            },
            status=status.HTTP_201_CREATED
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@extend_schema(
    request=RegisterSerializer,
    responses={200: OpenApiResponse(description='Authenticated successfully'), 400: OpenApiResponse(description='Bad request'), 401: OpenApiResponse(description='Invalid credentials')},
)
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthAnonRateThrottle])
def signin_user(request):
    email = request.data.get('email')
    password = request.data.get('password')
    role = request.data.get('role', 'staff')

    if not email or not password:
        return Response(
            {"detail": "Please provide both email and password."},
            status=status.HTTP_400_BAD_REQUEST
        )

    user = authenticate(request, email=email, password=password)

    if user is not None:
        if not user.is_active:
            return Response(
                {"detail": "This account is inactive. Please contact system administrator."},
                status=status.HTTP_403_FORBIDDEN
            )

        if not user.is_verified and not user.is_superuser:
            return Response(
                {
                    "detail": "Please verify your email address before signing in. Check your inbox for the verification link.",
                    "code": "email_not_verified",
                },
                status=status.HTTP_403_FORBIDDEN
            )

        if user.role != role and not user.is_superuser:
            return Response(
                {"detail": f"Access denied. Account is not registered as an {role}."},
                status=status.HTTP_403_FORBIDDEN
            )

        refresh = RefreshToken.for_user(user)

        return Response({
            "message": "Authenticated successfully",
            "tokens": {
                "refresh": str(refresh),
                "access": str(refresh.access_token),
            },
            "user": {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role,
            }
        }, status=status.HTTP_200_OK)

    return Response(
        {"detail": "Invalid email or password."},
        status=status.HTTP_401_UNAUTHORIZED
    )


@extend_schema(
    request=inline_serializer(
        name='VerifyEmailRequest',
        fields={'uid': serializers.CharField(), 'token': serializers.CharField()},
    ),
    responses={200: OpenApiResponse(description='Email verified'), 400: OpenApiResponse(description='Invalid or expired link')},
)
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthAnonRateThrottle])
def verify_email(request):
    uid = request.data.get('uid')
    token = request.data.get('token')

    if not uid or not token:
        return Response({"detail": "Missing verification link parameters."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        user_pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=user_pk)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        return Response({"detail": "This verification link is invalid."}, status=status.HTTP_400_BAD_REQUEST)

    if user.is_verified:
        return Response({"detail": "This account is already verified. You can sign in now."}, status=status.HTTP_200_OK)

    if not email_verification_token.check_token(user, token):
        return Response({"detail": "This verification link is invalid or has expired."}, status=status.HTTP_400_BAD_REQUEST)

    user.is_verified = True
    user.save(update_fields=['is_verified'])
    return Response({"detail": "Email verified successfully. You can sign in now."}, status=status.HTTP_200_OK)


@extend_schema(
    request=inline_serializer(name='ResendVerificationRequest', fields={'email': serializers.EmailField()}),
    responses={200: OpenApiResponse(description='If an unverified account exists, an email was sent')},
)
@api_view(['POST'])
@permission_classes([AllowAny])
@throttle_classes([AuthAnonRateThrottle])
def resend_verification(request):
    email = request.data.get('email')
    generic_response = Response(
        {"detail": "If an unverified account exists for that email, a new verification link has been sent."},
        status=status.HTTP_200_OK
    )
    if not email:
        return generic_response

    # Same response either way so this endpoint can't be used to enumerate
    # registered emails or verification status.
    user = User.objects.filter(email__iexact=email).first()
    if user and not user.is_verified:
        send_verification_email(user)
    return generic_response


# ---------------------------------------------------------------------------
# TASKS
# ---------------------------------------------------------------------------

class TaskListCreateView(generics.ListCreateAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if _is_admin(user):
            return Task.objects.all()
        # Staff only ever see tasks assigned to them — not tasks they created,
        # since staff can no longer create tasks at all.
        return Task.objects.filter(assignee=user)

    def create(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response(
                {"detail": "Only administrators can create tasks."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        task = serializer.save(created_by=self.request.user)
        _broadcast_task('task.created', task)


class TaskDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if _is_admin(user):
            return Task.objects.all()
        return Task.objects.filter(assignee=user)

    def update(self, request, *args, **kwargs):
        # Staff can view their assigned task detail, but only an admin can change
        # it (status, reassignment, etc). Staff request completion via the
        # dedicated request-completion endpoint instead.
        if not _is_admin(request.user):
            return Response(
                {"detail": "Only administrators can update tasks."},
                status=status.HTTP_403_FORBIDDEN
            )
        # If an admin is confirming completion, clear the pending review flag.
        data = request.data
        if isinstance(data, dict) and data.get('status') == 'complete':
            data['completion_requested'] = False
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        task = serializer.save()
        _broadcast_task('task.updated', task)

    def destroy(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response(
                {"detail": "Only administrators can delete tasks."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().destroy(request, *args, **kwargs)


class RequestTaskCompletionView(generics.GenericAPIView):
    """
    POST /api/tasks/<id>/request-completion/

    Lets the assignee (staff) flag a task as ready for review, without
    letting them change its status directly. Logs an ActivityLog entry and
    broadcasts both the task update and the activity entry in real time so
    admins see it immediately without refreshing.
    """
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            task = Task.objects.get(pk=pk)
        except Task.DoesNotExist:
            return Response({"detail": "Task not found."}, status=status.HTTP_404_NOT_FOUND)

        if task.assignee_id != request.user.id:
            return Response(
                {"detail": "You can only request a completion review for tasks assigned to you."},
                status=status.HTTP_403_FORBIDDEN
            )

        if task.status == 'complete':
            return Response(
                {"detail": "This task is already marked complete."},
                status=status.HTTP_400_BAD_REQUEST
            )

        task.completion_requested = True
        task.save(update_fields=['completion_requested'])
        _broadcast_task('task.updated', task)

        activity = ActivityLog.objects.create(
            user=request.user,
            action=f'requested a completion review for "{task.title}"',
            related_task=task
        )
        _broadcast_activity(activity)

        serializer = self.get_serializer(task)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# ACTIVITY LOG
# ---------------------------------------------------------------------------

class ActivityLogListView(generics.ListAPIView):
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if _is_admin(user):
            return ActivityLog.objects.all()[:20]
        return ActivityLog.objects.filter(user=user)[:20]


class ActivityMarkAllReadView(generics.GenericAPIView):
    """
    POST /api/activity/mark-all-read/

    Marks every activity entry currently visible to this user (same scoping
    as ActivityLogListView) as read by them, specifically. Doesn't affect
    other users' read state on the same shared entries.
    """
    serializer_class = ActivityLogSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiResponse(description='All caught up.')})
    def post(self, request):
        user = request.user
        if _is_admin(user):
            queryset = ActivityLog.objects.all()[:20]
        else:
            queryset = ActivityLog.objects.filter(user=user)[:20]

        for activity in queryset:
            activity.read_by.add(user)

        return Response({"detail": "All caught up."}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# BOOKINGS
# ---------------------------------------------------------------------------

class BookingListCreateView(generics.ListCreateAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_superuser:
            return Booking.objects.all()
        return Booking.objects.filter(client=user)

    def perform_create(self, serializer):
        serializer.save(client=self.request.user)


class BookingDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_superuser:
            return Booking.objects.all()
        return Booking.objects.filter(client=user)


# ---------------------------------------------------------------------------
# DOCUMENTS
# ---------------------------------------------------------------------------

class DocumentListCreateView(generics.ListCreateAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_superuser:
            return Document.objects.all()
        return Document.objects.filter(uploaded_by=user) | Document.objects.filter(assigned_to=user)

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class DocumentDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_superuser:
            return Document.objects.all()
        return Document.objects.filter(uploaded_by=user) | Document.objects.filter(assigned_to=user) | Document.objects.filter(assigned_to=user)


# ---------------------------------------------------------------------------
# INVOICES
# ---------------------------------------------------------------------------

class InvoiceListCreateView(generics.ListCreateAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_superuser:
            return Invoice.objects.all()
        return Invoice.objects.filter(client=user)


class InvoiceDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin' or user.is_superuser:
            return Invoice.objects.all()
        return Invoice.objects.filter(client=user)


# ---------------------------------------------------------------------------
# PLATFORM SETTINGS
# ---------------------------------------------------------------------------

class PlatformSettingsView(generics.RetrieveUpdateAPIView):
    serializer_class = PlatformSettingsSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return PlatformSettings.load()

    def update(self, request, *args, **kwargs):
        if not _is_admin(request.user):
            return Response(
                {"detail": "Only administrators can update platform settings."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)


class RotateSecretKeyView(generics.GenericAPIView):
    serializer_class = PlatformSettingsSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiResponse(description='Secret key rotation timestamp updated.')})
    def post(self, request):
        if not _is_admin(request.user):
            return Response(
                {"detail": "Only administrators can rotate the secret key."},
                status=status.HTTP_403_FORBIDDEN
            )

        settings_obj = PlatformSettings.load()
        settings_obj.secret_key_rotated_at = timezone.now()
        settings_obj.updated_by = request.user
        settings_obj.save(update_fields=['secret_key_rotated_at', 'updated_by', 'updated_at'])

        return Response(
            {
                "detail": "Secret key rotation timestamp updated.",
                "secret_key_rotated_at": settings_obj.secret_key_rotated_at
            },
            status=status.HTTP_200_OK
        )


# ---------------------------------------------------------------------------
# USERS / TEAM
# ---------------------------------------------------------------------------

class UserListView(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]


class UserDetailView(generics.RetrieveDestroyAPIView):
    """Admin-only. DELETE permanently removes the account and, via CASCADE
    on the FKs below, everything tied to it:
      - ActivityLog entries where they're the actor (ActivityLog.user)
      - Documents they uploaded (Document.uploaded_by) — including the
        underlying Cloudinary file's DB record, though note Cloudinary
        itself isn't cleaned up here (see NOTE below); this mirrors the
        existing gap in DocumentDetailView, not something new
    Tasks/Bookings/Invoices/Documents assigned-but-not-owned by them use
    SET_NULL, so those records survive with the link cleared rather than
    disappearing. This is irreversible — there's no undo."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]

    def perform_destroy(self, instance):
        if instance.pk == self.request.user.pk:
            raise PermissionDenied("You can't remove your own account.")

        if instance.role == 'admin' or instance.is_superuser:
            other_active_admins = User.objects.filter(
                models.Q(role='admin') | models.Q(is_superuser=True),
                is_active=True,
            ).exclude(pk=instance.pk)
            if not other_active_admins.exists():
                raise PermissionDenied("You can't remove the last active administrator.")

        # NOTE: this deletes the Document *rows* (via CASCADE) but does not
        # call Cloudinary's API to remove the underlying file blobs, so
        # deleted staff's uploads become orphaned/unreferenced in Cloudinary
        # storage rather than actually freed. Fixing that requires wiring a
        # pre_delete signal (or overriding this method) to call
        # cloudinary.uploader.destroy() per file first — out of scope here
        # since DocumentDetailView's own delete has the same gap already.
        instance.delete()