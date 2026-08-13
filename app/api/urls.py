from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    register_user, signin_user, verify_email, resend_verification,
    UserListView, UserDetailView,
    TaskListCreateView, TaskDetailView, RequestTaskCompletionView,
    ActivityLogListView, ActivityMarkAllReadView,
    BookingListCreateView, BookingDetailView,
    DocumentListCreateView, DocumentDetailView,
    InvoiceListCreateView, InvoiceDetailView,
    PlatformSettingsView, RotateSecretKeyView,
)

urlpatterns = [
    path('auth/signup/', register_user, name='register_user'),
    path('auth/signin/', signin_user, name='signin_user'),
    path('auth/verify-email/', verify_email, name='verify_email'),
    path('auth/resend-verification/', resend_verification, name='resend_verification'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('users/', UserListView.as_view(), name='user-list'),
    path('users/<int:pk>/', UserDetailView.as_view(), name='user-detail'),

    path('tasks/', TaskListCreateView.as_view(), name='task-list'),
    path('tasks/<int:pk>/', TaskDetailView.as_view(), name='task-detail'),
    path('tasks/<int:pk>/request-completion/', RequestTaskCompletionView.as_view(), name='task-request-completion'),

    path('activity/', ActivityLogListView.as_view(), name='activity-list'),
    path('activity/mark-all-read/', ActivityMarkAllReadView.as_view(), name='activity-mark-all-read'),

    path('bookings/', BookingListCreateView.as_view(), name='booking-list'),
    path('bookings/<int:pk>/', BookingDetailView.as_view(), name='booking-detail'),

    path('documents/', DocumentListCreateView.as_view(), name='document-list'),
    path('documents/<int:pk>/', DocumentDetailView.as_view(), name='document-detail'),

    path('invoices/', InvoiceListCreateView.as_view(), name='invoice-list'),
    path('invoices/<int:pk>/', InvoiceDetailView.as_view(), name='invoice-detail'),

    path('settings/', PlatformSettingsView.as_view(), name='platform-settings'),
    path('settings/rotate-secret/', RotateSecretKeyView.as_view(), name='rotate-secret'),
]