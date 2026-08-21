from rest_framework.permissions import BasePermission
from apps.accounts.models import Role


class HasRole(BasePermission):
    """
    Base permission class to check if an authenticated user possesses
    one of the specified allowed roles.
    """
    allowed_roles = []

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser or request.user.role == Role.ADMIN:
            return True
        return request.user.role in self.allowed_roles


class IsShipper(HasRole):
    """Permission check for Shippers or Admin."""
    allowed_roles = [Role.SHIPPER]


class IsTransporter(HasRole):
    """Permission check for Transporters or Admin."""
    allowed_roles = [Role.TRANSPORTER]


class IsDriver(HasRole):
    """Permission check for Drivers or Admin."""
    allowed_roles = [Role.DRIVER]


class IsFreightForwarder(HasRole):
    """Permission check for Freight Forwarders or Admin."""
    allowed_roles = [Role.FREIGHT_FORWARDER]


class IsCustomsStaff(HasRole):
    """Permission check for Customs Staff or Admin."""
    allowed_roles = [Role.CUSTOMS_STAFF]


class IsAdmin(BasePermission):
    """
    Permission check strictly for Platform Administrators or Superusers.
    """
    def has_permission(self, request, view):
        return bool(
            request.user and
            request.user.is_authenticated and
            (request.user.role == Role.ADMIN or request.user.is_staff or request.user.is_superuser)
        )


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level authorization permission.
    Allows access if the requesting user is the owner of the object,
    or if the requesting user is a platform Admin.
    """
    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        # Admins have global object access
        if request.user.role == Role.ADMIN or request.user.is_staff or request.user.is_superuser:
            return True

        # If the object is the User model itself
        if hasattr(obj, 'pk') and getattr(obj, 'pk') == request.user.pk and type(obj).__name__ == 'User':
            return True

        # If the object has a 'user' attribute (e.g. Profile or Resource)
        if hasattr(obj, 'user'):
            return obj.user == request.user

        return False
