import os
import hashlib
import uuid
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from django.core.files.storage import default_storage
from rest_framework.exceptions import PermissionDenied, ValidationError
from apps.accounts.models import Role, VerificationStatus, TransporterProfile, TransporterVerificationAudit, DriverProfile
from apps.marketplace.models import (
    Vehicle,
    CargoLoad,
    LoadStatus,
    Bid,
    BidStatus,
    Shipment,
    ShipmentStatus,
    LocationUpdate,
    ShipmentMilestone,
    DocumentType,
    ShipmentDocument,
    CargoCondition,
    PODConfirmationStatus,
    ProofOfDelivery,
)


class VerificationService:
    """
    Domain service managing Transporter verification lifecycle and load acceptance authorization.
    """
    @classmethod

    def verify_transporter(cls, transporter: TransporterProfile, admin_user, reason: str = ""):
        """
        Transitions a Transporter's verification status to VERIFIED with audit record.
        """
        if not (admin_user.is_superuser or admin_user.role == Role.ADMIN or admin_user.is_staff):
            raise PermissionDenied("Only administrators can verify transporters.")

        with transaction.atomic():
            previous_status = transporter.verification_status
            transporter.verification_status = VerificationStatus.VERIFIED
            transporter.save()

            audit = TransporterVerificationAudit.objects.create(
                transporter=transporter,
                performed_by=admin_user,
                previous_status=previous_status,
                new_status=VerificationStatus.VERIFIED,
                reason=reason or "Transporter legal verification documents approved."
            )

        return transporter, audit

    @classmethod

    def suspend_transporter(cls, transporter: TransporterProfile, admin_user, reason: str = ""):
        """
        Transitions a Transporter's verification status to SUSPENDED with audit record.
        """
        if not (admin_user.is_superuser or admin_user.role == Role.ADMIN or admin_user.is_staff):
            raise PermissionDenied("Only administrators can suspend transporters.")

        with transaction.atomic():
            previous_status = transporter.verification_status
            transporter.verification_status = VerificationStatus.SUSPENDED
            transporter.save()

            audit = TransporterVerificationAudit.objects.create(
                transporter=transporter,
                performed_by=admin_user,
                previous_status=previous_status,
                new_status=VerificationStatus.SUSPENDED,
                reason=reason or "Transporter account suspended by administrator."
            )

        return transporter, audit

    @classmethod

    def can_accept_load(cls, user_or_transporter) -> bool:
        """
        CRITICAL ACCEPTANCE CHECK:
        Enforces that only VERIFIED transporters can accept bookings or loads.
        Returns True if VERIFIED, False if PENDING or SUSPENDED.
        """
        transporter = None
        if isinstance(user_or_transporter, TransporterProfile):
            transporter = user_or_transporter
        elif hasattr(user_or_transporter, 'transporter_profile'):
            transporter = user_or_transporter.transporter_profile
        else:
            return False

        return transporter is not None and transporter.verification_status == VerificationStatus.VERIFIED


class FleetService:
    """
    Domain service for fleet vehicle management.
    """
    @classmethod

    def add_vehicle(cls, transporter: TransporterProfile, vehicle_data: dict) -> Vehicle:
        """
        Adds a vehicle to a transporter's fleet.
        """
        plate_number = vehicle_data.get('plate_number')
        if Vehicle.objects.filter(plate_number__iexact=plate_number).exists():
            raise ValidationError({'plate_number': 'A vehicle with this plate number already exists.'})

        vehicle = Vehicle.objects.create(
            transporter=transporter,
            **vehicle_data
        )
        return vehicle


class LoadService:
    """
    Domain service for cargo load management.
    """
    @classmethod

    def create_load(cls, shipper_profile, load_data: dict) -> CargoLoad:
        """
        Creates a new posted cargo load.
        """
        return CargoLoad.objects.create(
            shipper=shipper_profile,
            **load_data
        )

    @classmethod

    def cancel_load(cls, load: CargoLoad, user) -> CargoLoad:
        """
        Cancels a posted load if not yet assigned or delivered.
        """
        if not (user.is_superuser or user.role == Role.ADMIN or load.shipper.user == user):
            raise PermissionDenied("Only the load owner or an administrator can cancel this load.")

        if load.status in [LoadStatus.ASSIGNED]:
            raise ValidationError("Cannot cancel a load that has already been assigned.")

        load.status = LoadStatus.CANCELLED
        load.save()

        # Mark all pending bids as rejected
        load.bids.filter(status=BidStatus.SUBMITTED).update(status=BidStatus.REJECTED)
        return load


class BiddingService:
    """
    Domain service for spot market bidding and atomic bid acceptance.
    """
    @classmethod

    def submit_bid(cls, transporter_user, load: CargoLoad, bid_data: dict) -> Bid:
        """
        Submits a competitive spot market bid on a load.
        Enforces transporter verification status check.
        """
        # CRITICAL VERIFICATION CHECK
        if not VerificationService.can_accept_load(transporter_user):
            raise PermissionDenied("Unverified or suspended transporters are not permitted to submit bids on loads.")

        if load.status != LoadStatus.POSTED:
            raise ValidationError("Bids can only be submitted on loads that are actively POSTED.")

        transporter_profile = transporter_user.transporter_profile

        # Check existing bid
        if Bid.objects.filter(load=load, transporter=transporter_profile).exists():
            raise ValidationError("You have already submitted a bid on this load.")

        # Validate proposed vehicle
        proposed_vehicle = bid_data.get('proposed_vehicle')
        if proposed_vehicle:
            if proposed_vehicle.transporter != transporter_profile:
                raise ValidationError({'proposed_vehicle': 'The proposed vehicle must belong to your fleet.'})
            if not proposed_vehicle.is_active:
                raise ValidationError({'proposed_vehicle': 'The proposed vehicle is inactive.'})

        bid = Bid.objects.create(
            load=load,
            transporter=transporter_profile,
            **bid_data
        )
        return bid

    @classmethod

    def accept_bid(cls, shipper_user, bid: Bid) -> CargoLoad:
        """
        ATOMIC BID ACCEPTANCE WORKFLOW:
        - Validates shipper ownership.
        - Updates winning bid to ACCEPTED.
        - Updates all competing bids on load to REJECTED.
        - Binds assigned transporter and vehicle to load.
        - Sets load status to ASSIGNED.
        - Automatically initializes Shipment execution record (Phase 6).
        """
        load = bid.load

        if not (shipper_user.is_superuser or shipper_user.role == Role.ADMIN or load.shipper.user == shipper_user):
            raise PermissionDenied("Only the load owner or an administrator can accept bids on this load.")

        if load.status != LoadStatus.POSTED:
            raise ValidationError("Bids can only be accepted for loads currently in POSTED status.")

        if bid.status != BidStatus.SUBMITTED:
            raise ValidationError("Only submitted bids can be accepted.")

        with transaction.atomic():
            # Update winning bid
            bid.status = BidStatus.ACCEPTED
            bid.save()

            # Reject all other active bids on this load
            load.bids.filter(status=BidStatus.SUBMITTED).exclude(pk=bid.pk).update(status=BidStatus.REJECTED)

            # Assign load to transporter
            load.status = LoadStatus.ASSIGNED
            load.assigned_transporter = bid.transporter
            load.assigned_vehicle = bid.proposed_vehicle
            load.save()

            # PHASE 6 INTEGRATION: Initialize Shipment
            TrackingService.create_shipment_from_load(load)

        return load

    @classmethod

    def withdraw_bid(cls, transporter_user, bid: Bid) -> Bid:
        """
        Withdraws a pending bid submitted by a transporter.
        """
        if not (transporter_user.is_superuser or transporter_user.role == Role.ADMIN or bid.transporter.user == transporter_user):
            raise PermissionDenied("Only the bidding transporter can withdraw this bid.")

        if bid.status != BidStatus.SUBMITTED:
            raise ValidationError("Only submitted bids can be withdrawn.")

        bid.status = BidStatus.WITHDRAWN
        bid.save()
        return bid


class TrackingService:
    """
    Domain service managing shipment execution, milestone auditing, and real-time GPS tracking.
    """
    @classmethod

    def create_shipment_from_load(cls, load: CargoLoad, driver: DriverProfile = None) -> Shipment:
        """
        Creates a new Shipment execution record from an assigned load with unique tracking number.
        """
        if hasattr(load, 'shipment'):
            return load.shipment

        date_str = timezone.now().strftime("%Y%m%d")
        unique_suffix = str(uuid.uuid4().hex[:4]).upper()
        tracking_number = f"TRK-{date_str}-{load.id:04d}-{unique_suffix}"

        shipment = Shipment.objects.create(
            tracking_number=tracking_number,
            load=load,
            transporter=load.assigned_transporter,
            vehicle=load.assigned_vehicle,
            driver=driver,
            origin=load.origin,
            destination=load.destination,
            status=ShipmentStatus.CREATED
        )

        ShipmentMilestone.objects.create(
            shipment=shipment,
            status=ShipmentStatus.CREATED,
            location_name=load.origin,
            notes="Shipment initialized upon bid acceptance.",
            updated_by=load.shipper.user
        )

        return shipment

    @classmethod

    def assign_driver(cls, shipment: Shipment, driver: DriverProfile, user) -> Shipment:
        """
        Assigns a driver to an active shipment.
        """
        if not (user.is_superuser or user.role == Role.ADMIN or shipment.transporter.user == user):
            raise PermissionDenied("Only the assigned transporter or an administrator can assign a driver.")

        with transaction.atomic():
            shipment.driver = driver
            if shipment.status == ShipmentStatus.CREATED:
                shipment.status = ShipmentStatus.DRIVER_ASSIGNED
            shipment.save()

            ShipmentMilestone.objects.create(
                shipment=shipment,
                status=shipment.status,
                location_name=shipment.origin,
                notes=f"Driver {driver.user.get_full_name()} assigned to shipment.",
                updated_by=user
            )

        return shipment

    @classmethod

    def update_status(cls, shipment: Shipment, new_status: str, user, location_name: str = "", notes: str = "") -> Shipment:
        """
        Updates shipment execution status and creates milestone audit entry.
        """
        is_transporter = hasattr(user, 'transporter_profile') and shipment.transporter == user.transporter_profile
        is_driver = hasattr(user, 'driver_profile') and shipment.driver == user.driver_profile
        is_admin = user.is_superuser or user.role == Role.ADMIN

        if not (is_transporter or is_driver or is_admin or user == shipment.load.shipper.user):
            raise PermissionDenied("Only the assigned driver, transporter, or an administrator can update shipment status.")

        with transaction.atomic():
            shipment.status = new_status
            if new_status in [ShipmentStatus.AT_PICKUP, ShipmentStatus.IN_TRANSIT] and not shipment.actual_pickup_time:
                shipment.actual_pickup_time = timezone.now()
            elif new_status == ShipmentStatus.DELIVERED and not shipment.actual_delivery_time:
                shipment.actual_delivery_time = timezone.now()
            shipment.save()

            ShipmentMilestone.objects.create(
                shipment=shipment,
                status=new_status,
                location_name=location_name or (shipment.origin if new_status != ShipmentStatus.DELIVERED else shipment.destination),
                notes=notes or f"Shipment status updated to {new_status}.",
                updated_by=user
            )

        return shipment

    @classmethod

    def record_location(cls, shipment: Shipment, latitude: float, longitude: float, speed_kmh: float = None, heading_degrees: float = None, location_name: str = "", user=None) -> LocationUpdate:
        """
        Records a real-time GPS telemetry ping for a shipment in transit.
        """
        location_update = LocationUpdate.objects.create(
            shipment=shipment,
            latitude=latitude,
            longitude=longitude,
            speed_kmh=speed_kmh,
            heading_degrees=heading_degrees,
            location_name=location_name,
            recorded_by=user
        )
        return location_update


# ============================================================================
# PHASE 7: DOCUMENT MANAGEMENT & DIGITAL PROOF OF DELIVERY (e-POD) SERVICES
# ============================================================================

ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']
DISALLOWED_EXTENSIONS = ['.exe', '.sh', '.bat', '.py', '.js', '.php', '.bin', '.cmd']
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class DocumentService:
    """
    Domain service for shipment logistics document upload, validation, and deletion.
    """
    @classmethod

    def upload_document(cls, shipment: Shipment, file_obj, document_type: str, user, notes: str = "") -> ShipmentDocument:
        """
        Validates file size (max 10MB), white-listed extension, calculates SHA-256 checksum,
        and saves ShipmentDocument record.
        """
        # Validate participant authorization
        is_shipper = hasattr(user, 'shipper_profile') and shipment.load.shipper == user.shipper_profile
        is_transporter = hasattr(user, 'transporter_profile') and shipment.transporter == user.transporter_profile
        is_driver = hasattr(user, 'driver_profile') and shipment.driver == user.driver_profile
        is_admin = user.is_superuser or user.role == Role.ADMIN

        if not (is_shipper or is_transporter or is_driver or is_admin):
            raise PermissionDenied("Only shipment participants or administrators can upload documents for this shipment.")

        # Sanitize filename & extract extension
        raw_name = os.path.basename(file_obj.name)
        ext = os.path.splitext(raw_name)[1].lower()

        if ext in DISALLOWED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
            raise ValidationError({'file': f"File extension '{ext}' is not permitted. Allowed extensions: {', '.join(ALLOWED_EXTENSIONS)}"})

        # Validate file size
        file_size = file_obj.size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValidationError({'file': f"File size ({file_size} bytes) exceeds maximum limit of 10 MB."})

        # Calculate SHA-256 checksum deterministically
        hasher = hashlib.sha256()
        for chunk in file_obj.chunks():
            hasher.update(chunk)
        checksum_sha256 = hasher.hexdigest()

        # Reset file pointer after reading chunks
        file_obj.seek(0)

        mime_type = getattr(file_obj, 'content_type', 'application/octet-stream')

        document = ShipmentDocument.objects.create(
            shipment=shipment,
            document_type=document_type,
            file=file_obj,
            file_name=raw_name,
            file_size_bytes=file_size,
            mime_type=mime_type,
            checksum_sha256=checksum_sha256,
            uploaded_by=user,
            notes=notes
        )

        return document

    @classmethod

    def delete_document(cls, document: ShipmentDocument, user):
        """
        Removes physical file and deletes document DB record.
        Restricted to uploader or Admin.
        """
        if not (user.is_superuser or user.role == Role.ADMIN or document.uploaded_by == user):
            raise PermissionDenied("Only the document uploader or an administrator can delete this document.")

        # Remove physical file safely
        if document.file and default_storage.exists(document.file.name):
            default_storage.delete(document.file.name)

        document.delete()


class PODService:
    """
    Domain service managing Digital Proof of Delivery (e-POD), delivery confirmation, and disputes.
    """
    @classmethod

    def create_pod(cls, shipment: Shipment, driver_user, pod_data: dict) -> ProofOfDelivery:
        """
        Creates e-POD in SUBMITTED state and transitions shipment status to DELIVERED.
        """
        # Validate authorization
        is_transporter = hasattr(driver_user, 'transporter_profile') and shipment.transporter == driver_user.transporter_profile
        is_driver = hasattr(driver_user, 'driver_profile') and shipment.driver == driver_user.driver_profile
        is_admin = driver_user.is_superuser or driver_user.role == Role.ADMIN

        if not (is_transporter or is_driver or is_admin):
            raise PermissionDenied("Only the assigned driver, transporter, or an administrator can submit Proof of Delivery.")

        if hasattr(shipment, 'pod'):
            raise ValidationError("A Proof of Delivery has already been submitted for this shipment.")

        driver_profile = getattr(driver_user, 'driver_profile', None)

        with transaction.atomic():
            pod = ProofOfDelivery.objects.create(
                shipment=shipment,
                delivered_by_driver=driver_profile,
                confirmation_status=PODConfirmationStatus.SUBMITTED,
                **pod_data
            )

            # Transition shipment to DELIVERED status via TrackingService
            if shipment.status != ShipmentStatus.DELIVERED:
                TrackingService.update_status(
                    shipment=shipment,
                    new_status=ShipmentStatus.DELIVERED,
                    user=driver_user,
                    location_name=pod_data.get('delivery_location', shipment.destination),
                    notes=f"Digital Proof of Delivery submitted by {driver_user.get_full_name()}."
                )

        return pod

    @classmethod

    def confirm_pod(cls, pod: ProofOfDelivery, shipper_user) -> ProofOfDelivery:
        """
        Shipper confirms e-POD delivery. Sets status to CONFIRMED.
        """
        load_shipper = pod.shipment.load.shipper
        if not (shipper_user.is_superuser or shipper_user.role == Role.ADMIN or load_shipper.user == shipper_user):
            raise PermissionDenied("Only the load-owning shipper or an administrator can confirm Proof of Delivery.")

        if pod.confirmation_status == PODConfirmationStatus.CONFIRMED:
            return pod

        with transaction.atomic():
            pod.confirmation_status = PODConfirmationStatus.CONFIRMED
            pod.confirmed_by_shipper = shipper_user
            pod.confirmed_at = timezone.now()
            pod.save()

        return pod

    @classmethod

    def dispute_pod(cls, pod: ProofOfDelivery, shipper_user, dispute_reason: str) -> ProofOfDelivery:
        """
        Shipper disputes e-POD delivery with dispute reason.
        """
        load_shipper = pod.shipment.load.shipper
        if not (shipper_user.is_superuser or shipper_user.role == Role.ADMIN or load_shipper.user == shipper_user):
            raise PermissionDenied("Only the load-owning shipper or an administrator can dispute Proof of Delivery.")

        if not dispute_reason.strip():
            raise ValidationError({'dispute_reason': 'A dispute reason is required when disputing delivery.'})

        if pod.confirmation_status == PODConfirmationStatus.CONFIRMED:
            raise ValidationError("A confirmed Proof of Delivery cannot be disputed.")

        with transaction.atomic():
            pod.confirmation_status = PODConfirmationStatus.DISPUTED
            pod.dispute_reason = dispute_reason.strip()
            pod.save()

            # Record milestone audit for dispute
            ShipmentMilestone.objects.create(
                shipment=pod.shipment,
                status=pod.shipment.status,
                location_name=pod.delivery_location,
                notes=f"Delivery DISPUTED by Shipper: {dispute_reason}",
                updated_by=shipper_user
            )

        return pod
