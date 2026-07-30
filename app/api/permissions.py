from rest_framework import permissions

class IsAdminUser(permissions.BasePermission):
    """
    Allows access only to admin users or superusers.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and 
            request.user.is_authenticated and 
            (request.user.role == 'admin' or request.user.is_superuser)
        )


class IsOwnerOrAdmin(permissions.BasePermission):
    """
    Object-level permission to only allow owners/assignees of an object or
    admins to view/edit it.
    """
    def has_object_permission(self, request, view, obj):
        if not request.user or not request.user.is_authenticated:
            return False

        if request.user.role == 'admin' or request.user.is_superuser:
            return True

        # Check every applicable ownership/assignment attribute and grant
        # access if ANY of them match — don't stop at the first one found.
        # (A Document has both uploaded_by and assigned_to; either one
        # should grant access. The old version returned on the first
        # hasattr() match even when it was False, so an assigned-but-not-
        # uploading staff member was incorrectly denied.)
        owner_fields = ['client', 'uploaded_by', 'created_by', 'user']
        for field in owner_fields:
            if hasattr(obj, field) and getattr(obj, field) == request.user:
                return True

        if hasattr(obj, 'assigned_to') and obj.assigned_to == request.user:
            return True

        if hasattr(obj, 'assignee') and obj.assignee == request.user:
            return True

        return False