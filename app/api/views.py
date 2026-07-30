from rest_framework import status, generics, permissions
from django.contrib.auth import get_user_model, authenticate
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Task, ActivityLog, Booking, Document, Invoice
from .serializers import (
    RegisterSerializer, UserSerializer, TaskSerializer, ActivityLogSerializer,
    BookingSerializer, DocumentSerializer, InvoiceSerializer
)
from .permissions import IsOwnerOrAdmin, IsAdminUser

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
    permission_classes = [IsAuthenticated]

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
# USERS / TEAM
# ---------------------------------------------------------------------------

class UserListView(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]