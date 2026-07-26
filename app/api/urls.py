from django.urls import path
from .views import (
    register_user, signin_user, UserListView,
    TaskListCreateView, TaskDetailView, RequestTaskCompletionView,
    ActivityLogListView,
    BookingListCreateView, BookingDetailView,
    DocumentListCreateView, DocumentDetailView,
    InvoiceListCreateView, InvoiceDetailView,
)

urlpatterns = [
    path('auth/signup/', register_user, name='register_user'),
    path('auth/signin/', signin_user, name='signin_user'),
    path('users/', UserListView.as_view(), name='user-list'),

    path('tasks/', TaskListCreateView.as_view(), name='task-list'),
    path('tasks/<int:pk>/', TaskDetailView.as_view(), name='task-detail'),
    path('tasks/<int:pk>/request-completion/', RequestTaskCompletionView.as_view(), name='task-request-completion'),

    path('activity/', ActivityLogListView.as_view(), name='activity-list'),

    path('bookings/', BookingListCreateView.as_view(), name='booking-list'),
    path('bookings/<int:pk>/', BookingDetailView.as_view(), name='booking-detail'),

    path('documents/', DocumentListCreateView.as_view(), name='document-list'),
    path('documents/<int:pk>/', DocumentDetailView.as_view(), name='document-detail'),

    path('invoices/', InvoiceListCreateView.as_view(), name='invoice-list'),
    path('invoices/<int:pk>/', InvoiceDetailView.as_view(), name='invoice-detail'),
]