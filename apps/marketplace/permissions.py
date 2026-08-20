from rest_framework.permissions import BasePermission
from apps.accounts.models import Role, VerificationStatus
from apps.marketplace.services import VerificationService


class IsTransporterVerified(BasePermission):
    """
    CRITICAL PERMISSION CLASS:
    Ensures an operation is accessible only if the requesting user is a VERIFIED transporter (or Admin).
    Blocks PENDING or SUSPENDED transporters from load bidding / acceptance operations.
    """
    message = "Transporter verification is pending or suspended. Unverified transporters cannot perform load bidding operations."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.is_superuser or request.user.role == Role.ADMIN:
            return True

        if request.user.role != Role.TRANSPORTER:
            return False

        return VerificationService.can_accept_load(request.user)


class IsVehicleOwnerOrAdmin(BasePermission):
    """
    Object-level permission ensuring a Transporter can only access/modify
    vehicles belonging to their own fleet.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.is_superuser or request.user.role == Role.ADMIN:
            return True

        if hasattr(request.user, 'transporter_profile'):
            return obj.transporter == request.user.transporter_profile

        return False


class IsLoadOwnerOrAdmin(BasePermission):
    """
    Object-level permission ensuring only the load owner shipper (or Admin) can modify/cancel a load.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.is_superuser or request.user.role == Role.ADMIN:
            return True

        if hasattr(request.user, 'shipper_profile'):
            return obj.shipper == request.user.shipper_profile

        return False


class IsBidOwnerOrAdmin(BasePermission):
    """
    Object-level permission ensuring only the bidding transporter (or Admin) can modify/withdraw a bid.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if not (request.user and request.user.is_authenticated):
            return False

        if request.user.is_superuser or request.user.role == Role.ADMIN:
            return True

        if hasattr(request.user, 'transporter_profile'):
            return obj.transporter == request.user.transporter_profile

        return False


class IsShipmentParticipantOrAdmin(BasePermission):
    """
    Object-level permission ensuring only shipment participants
    (Shipper load owner, Transporter owner, assigned Driver, or Admin) can view/update shipment.
    """
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not (user and user.is_authenticated):
            return False

        if user.is_superuser or user.role == Role.ADMIN:
            return True

        # Shipper load owner
        if hasattr(user, 'shipper_profile') and obj.load.shipper == user.shipper_profile:
            return True

        # Transporter owner
        if hasattr(user, 'transporter_profile') and obj.transporter == user.transporter_profile:
            return True

        # Assigned driver
        if hasattr(user, 'driver_profile') and obj.driver == user.driver_profile:
            return True

        return False
