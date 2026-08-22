import os
import math
from datetime import timedelta
import hashlib
import uuid
from abc import ABC, abstractmethod
from decimal import Decimal
from datetime import date, datetime, timedelta
from django.db import transaction, IntegrityError
from django.utils import timezone
from django.core.files.storage import default_storage
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound

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
    PaymentStatus,
    FreightInvoice,
    SettlementStatus,
    FreightSettlement,
    Payment,
    PayoutStatus,
    TransporterPayout,
    PaymentDisputeStatus,
    PaymentDispute,
    OfflineSyncEventType,
    OfflineSyncStatus,
    OfflineSyncEvent,
    IncidentType,
    DriverIncidentReport,
    Route,
    RouteWaypoint,
    RouteRecalculation,
    RouteStatus,
    RouteDeviationStatus,
)


class VerificationService:
    """
    Domain service managing Transporter verification lifecycle and load acceptance authorization.
    """
    @classmethod

    def verify_transporter(cls, transporter: TransporterProfile, admin_user, reason: str = ""):
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
        return CargoLoad.objects.create(
            shipper=shipper_profile,
            **load_data
        )

    @classmethod

    def cancel_load(cls, load: CargoLoad, user) -> CargoLoad:
        if not (user.is_superuser or user.role == Role.ADMIN or load.shipper.user == user):
            raise PermissionDenied("Only the load owner or an administrator can cancel this load.")

        if load.status in [LoadStatus.ASSIGNED]:
            raise ValidationError("Cannot cancel a load that has already been assigned.")

        load.status = LoadStatus.CANCELLED
        load.save()

        load.bids.filter(status=BidStatus.SUBMITTED).update(status=BidStatus.REJECTED)
        return load


class BiddingService:
    """
    Domain service for spot market bidding and atomic bid acceptance.
    """
    @classmethod

    def submit_bid(cls, transporter_user, load: CargoLoad, bid_data: dict) -> Bid:
        if not VerificationService.can_accept_load(transporter_user):
            raise PermissionDenied("Unverified or suspended transporters are not permitted to submit bids on loads.")

        if load.status != LoadStatus.POSTED:
            raise ValidationError("Bids can only be submitted on loads that are actively POSTED.")

        transporter_profile = transporter_user.transporter_profile

        if Bid.objects.filter(load=load, transporter=transporter_profile).exists():
            raise ValidationError("You have already submitted a bid on this load.")

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
        load = bid.load

        if not (shipper_user.is_superuser or shipper_user.role == Role.ADMIN or load.shipper.user == shipper_user):
            raise PermissionDenied("Only the load owner or an administrator can accept bids on this load.")

        if load.status != LoadStatus.POSTED:
            raise ValidationError("Bids can only be accepted for loads currently in POSTED status.")

        if bid.status != BidStatus.SUBMITTED:
            raise ValidationError("Only submitted bids can be accepted.")

        with transaction.atomic():
            bid.status = BidStatus.ACCEPTED
            bid.save()

            load.bids.filter(status=BidStatus.SUBMITTED).exclude(pk=bid.pk).update(status=BidStatus.REJECTED)

            load.status = LoadStatus.ASSIGNED
            load.assigned_transporter = bid.transporter
            load.assigned_vehicle = bid.proposed_vehicle
            load.save()

            TrackingService.create_shipment_from_load(load)

        return load

    @classmethod

    def withdraw_bid(cls, transporter_user, bid: Bid) -> Bid:
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

    def update_status(cls, shipment: Shipment, new_status: str, user, location_name: str = "", notes: str = "", timestamp=None) -> Shipment:
        is_transporter = hasattr(user, 'transporter_profile') and shipment.transporter == user.transporter_profile
        is_driver = hasattr(user, 'driver_profile') and shipment.driver == user.driver_profile
        is_admin = user.is_superuser or user.role == Role.ADMIN

        if not (is_transporter or is_driver or is_admin or user == shipment.load.shipper.user):
            raise PermissionDenied("Only the assigned driver, transporter, or an administrator can update shipment status.")

        event_time = timestamp or timezone.now()

        with transaction.atomic():
            shipment.status = new_status
            if new_status in [ShipmentStatus.AT_PICKUP, ShipmentStatus.IN_TRANSIT] and not shipment.actual_pickup_time:
                shipment.actual_pickup_time = event_time
            elif new_status == ShipmentStatus.DELIVERED and not shipment.actual_delivery_time:
                shipment.actual_delivery_time = event_time
            shipment.save()

            milestone = ShipmentMilestone.objects.create(
                shipment=shipment,
                status=new_status,
                location_name=location_name or (shipment.origin if new_status != ShipmentStatus.DELIVERED else shipment.destination),
                notes=notes or f"Shipment status updated to {new_status}.",
                updated_by=user
            )
            if timestamp:
                milestone.timestamp = timestamp
                milestone.save(update_fields=['timestamp'])

        return shipment

    @classmethod

    def record_location(cls, shipment: Shipment, latitude: float, longitude: float, speed_kmh: float = None, heading_degrees: float = None, location_name: str = "", user=None, timestamp=None) -> LocationUpdate:
        if latitude < -90 or latitude > 90:
            raise ValidationError({'latitude': 'Latitude must be between -90 and 90 degrees.'})
        if longitude < -180 or longitude > 180:
            raise ValidationError({'longitude': 'Longitude must be between -180 and 180 degrees.'})

        location_update = LocationUpdate.objects.create(
            shipment=shipment,
            latitude=latitude,
            longitude=longitude,
            speed_kmh=speed_kmh,
            heading_degrees=heading_degrees,
            location_name=location_name,
            recorded_by=user
        )
        if timestamp:
            location_update.timestamp = timestamp
            location_update.save(update_fields=['timestamp'])
        # A new authoritative GPS observation is the trigger for an ETA refresh.
        ETAService.recalculate(shipment)
        return location_update


class ETAService:
    """Explainable ETA baseline using consecutive GPS observations.

    It deliberately does not claim ML accuracy: until historical corridor data is
    available, the estimate is based on observed speed and the load's promised
    delivery date as the authoritative upper planning bound.
    """
    MIN_SPEED_KMH = 15.0
    DEFAULT_SPEED_KMH = 45.0

    @staticmethod
    def _distance_km(first, second):
        radius = 6371.0
        lat1, lon1, lat2, lon2 = map(math.radians, [float(first.latitude), float(first.longitude), float(second.latitude), float(second.longitude)])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @classmethod
    def recalculate(cls, shipment):
        updates = list(shipment.location_updates.order_by('-timestamp')[:2])
        latest = updates[0] if updates else None
        speed = float(latest.speed_kmh) if latest and latest.speed_kmh else None
        observed = False
        if len(updates) == 2:
            elapsed_hours = (updates[0].timestamp - updates[1].timestamp).total_seconds() / 3600
            if elapsed_hours > 0:
                speed = max(cls.MIN_SPEED_KMH, cls._distance_km(updates[0], updates[1]) / elapsed_hours)
                observed = True
        speed = speed or cls.DEFAULT_SPEED_KMH
        due = timezone.make_aware(timezone.datetime.combine(shipment.load.delivery_date, timezone.datetime.max.time()))
        now = timezone.now()
        remaining_hours = max(1.0, (due - now).total_seconds() / 3600)
        eta = now + timedelta(hours=remaining_hours)
        confidence = 75 if observed else (60 if latest else 35)
        shipment.estimated_arrival_at = eta
        shipment.eta_updated_at = now
        shipment.eta_confidence = confidence
        shipment.eta_basis = {'method': 'observed_gps_speed' if observed else 'planning_baseline', 'speed_kmh': round(speed, 2), 'location_update_id': latest.id if latest else None}
        shipment.save(update_fields=['estimated_arrival_at', 'eta_updated_at', 'eta_confidence', 'eta_basis', 'updated_at'])
        return shipment


ALLOWED_EXTENSIONS = ['.pdf', '.png', '.jpg', '.jpeg']
DISALLOWED_EXTENSIONS = ['.exe', '.sh', '.bat', '.py', '.js', '.php', '.bin', '.cmd']
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class DocumentService:
    """
    Domain service for shipment logistics document upload, validation, and deletion.
    """
    @classmethod

    def upload_document(cls, shipment: Shipment, file_obj, document_type: str, user, notes: str = "") -> ShipmentDocument:
        is_shipper = hasattr(user, 'shipper_profile') and shipment.load.shipper == user.shipper_profile
        is_transporter = hasattr(user, 'transporter_profile') and shipment.transporter == user.transporter_profile
        is_driver = hasattr(user, 'driver_profile') and shipment.driver == user.driver_profile
        is_admin = user.is_superuser or user.role == Role.ADMIN

        if not (is_shipper or is_transporter or is_driver or is_admin):
            raise PermissionDenied("Only shipment participants or administrators can upload documents for this shipment.")

        raw_name = os.path.basename(file_obj.name)
        ext = os.path.splitext(raw_name)[1].lower()

        if ext in DISALLOWED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
            raise ValidationError({'file': f"File extension '{ext}' is not permitted. Allowed extensions: {', '.join(ALLOWED_EXTENSIONS)}"})

        file_size = file_obj.size
        if file_size > MAX_FILE_SIZE_BYTES:
            raise ValidationError({'file': f"File size ({file_size} bytes) exceeds maximum limit of 10 MB."})

        hasher = hashlib.sha256()
        for chunk in file_obj.chunks():
            hasher.update(chunk)
        checksum_sha256 = hasher.hexdigest()
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
        if not (user.is_superuser or user.role == Role.ADMIN or document.uploaded_by == user):
            raise PermissionDenied("Only the document uploader or an administrator can delete this document.")

        if document.file and default_storage.exists(document.file.name):
            default_storage.delete(document.file.name)

        document.delete()


class PODService:
    """
    Domain service managing Digital Proof of Delivery (e-POD), delivery confirmation, and disputes.
    """
    @classmethod

    def create_pod(cls, shipment: Shipment, driver_user, pod_data: dict) -> ProofOfDelivery:
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

            ShipmentMilestone.objects.create(
                shipment=pod.shipment,
                status=pod.shipment.status,
                location_name=pod.delivery_location,
                notes=f"Delivery DISPUTED by Shipper: {dispute_reason}",
                updated_by=shipper_user
            )

        return pod


# ============================================================================
# PHASE 8: PAYMENT PROVIDER ABSTRACTION & FREIGHT SETTLEMENT SERVICES (FR-10)
# ============================================================================

class PaymentProvider(ABC):
    """
    Abstract interface for payment gateway providers. Isolates domain logic
    from external payment implementations (Telebirr, Mobile Money, Banks).
    """
    @abstractmethod
    def initiate_payment(self, reference_id: str, amount: Decimal, currency: str, payer_info: dict) -> dict:
        pass

    @abstractmethod
    def verify_payment(self, provider_transaction_id: str) -> dict:
        pass

    @abstractmethod
    def get_transaction_status(self, provider_transaction_id: str) -> str:
        pass


class MockPaymentProvider(PaymentProvider):
    """
    Deterministic Mock Payment Provider for local development & automated testing.
    """
    def initiate_payment(self, reference_id: str, amount: Decimal, currency: str, payer_info: dict) -> dict:
        return {
            "status": PaymentStatus.SUCCEEDED,
            "provider_transaction_id": f"MOCK-TXN-{reference_id}",
            "amount": amount,
            "currency": currency,
            "message": "Mock payment successfully processed."
        }

    def verify_payment(self, provider_transaction_id: str) -> dict:
        return {
            "status": PaymentStatus.SUCCEEDED,
            "provider_transaction_id": provider_transaction_id,
            "verified": True
        }

    def get_transaction_status(self, provider_transaction_id: str) -> str:
        return PaymentStatus.SUCCEEDED


class InvoiceService:
    """
    Domain service for freight invoicing.
    """
    @classmethod

    def generate_invoice(cls, shipment: Shipment, issuer_user=None) -> FreightInvoice:
        if shipment.invoices.filter(status__in=[PaymentStatus.PENDING, PaymentStatus.SUCCEEDED]).exists():
            return shipment.invoices.filter(status__in=[PaymentStatus.PENDING, PaymentStatus.SUCCEEDED]).first()

        accepted_bids = shipment.load.bids.filter(status=BidStatus.ACCEPTED)
        if accepted_bids.exists():
            amount = accepted_bids.first().amount
        else:
            amount = shipment.load.target_price

        date_str = timezone.now().strftime("%Y%m%d")
        unique_suffix = str(uuid.uuid4().hex[:4]).upper()
        invoice_number = f"INV-{date_str}-{shipment.id:04d}-{unique_suffix}"

        due_date = date.today() + timedelta(days=7)

        invoice = FreightInvoice.objects.create(
            invoice_number=invoice_number,
            shipment=shipment,
            issuer=issuer_user or shipment.transporter.user,
            payer=shipment.load.shipper.user,
            subtotal_amount=amount,
            commission_amount=Decimal('0.00'),
            total_amount=amount,
            currency='ETB',
            status=PaymentStatus.PENDING,
            due_date=due_date,
            notes=f"Freight invoice for shipment {shipment.tracking_number} ({shipment.origin} -> {shipment.destination})"
        )
        return invoice


class SettlementService:
    """
    Domain service for freight settlement, calculating gross freight, platform commission,
    transporter net payable, and enforcing e-POD delivery verification.
    """
    DEFAULT_COMMISSION_RATE = Decimal('0.0500')  # Configurable 5% platform commission

    @classmethod

    def create_settlement_for_shipment(cls, shipment: Shipment, commission_rate: Decimal = None) -> FreightSettlement:
        if hasattr(shipment, 'settlement'):
            return shipment.settlement

        if commission_rate is None:
            commission_rate = cls.DEFAULT_COMMISSION_RATE

        accepted_bids = shipment.load.bids.filter(status=BidStatus.ACCEPTED)
        if accepted_bids.exists():
            gross_amount = accepted_bids.first().amount
        else:
            gross_amount = shipment.load.target_price

        # Decimal arithmetic
        commission_amount = (gross_amount * commission_rate).quantize(Decimal('0.01'))
        net_payable = gross_amount - commission_amount

        invoice = InvoiceService.generate_invoice(shipment)

        # Check e-POD delivery readiness
        is_ready = shipment.status == ShipmentStatus.DELIVERED and hasattr(shipment, 'pod')
        initial_status = SettlementStatus.READY if is_ready else SettlementStatus.PENDING

        settlement = FreightSettlement.objects.create(
            shipment=shipment,
            invoice=invoice,
            gross_freight_amount=gross_amount,
            commission_rate=commission_rate,
            platform_commission_amount=commission_amount,
            transporter_net_payable=net_payable,
            status=initial_status
        )
        return settlement


class PaymentService:
    """
    Domain service managing payment initiation, idempotency checks, and confirmation.
    """
    @classmethod

    def initiate_payment(cls, settlement: FreightSettlement, payer_user, idempotency_key: str, provider_name: str = "MOCK") -> Payment:
        # Authorization check
        is_shipper = hasattr(payer_user, 'shipper_profile') and settlement.shipment.load.shipper == payer_user.shipper_profile
        is_admin = payer_user.is_superuser or payer_user.role == Role.ADMIN

        if not (is_shipper or is_admin):
            raise PermissionDenied("Only the load-owning shipper or an administrator can initiate payment for this settlement.")

        if settlement.gross_freight_amount <= 0:
            raise ValidationError("Settlement amount must be greater than 0 ETB.")

        # Idempotency Check
        existing_payment = Payment.objects.filter(idempotency_key=idempotency_key).first()
        if existing_payment:
            return existing_payment

        provider = MockPaymentProvider()

        with transaction.atomic():
            payment = Payment.objects.create(
                idempotency_key=idempotency_key,
                shipment=settlement.shipment,
                settlement=settlement,
                payer=payer_user,
                amount=settlement.gross_freight_amount,
                currency='ETB',
                provider=provider_name,
                payment_method='MOCK_TRANSFER',
                status=PaymentStatus.INITIATED
            )

            # Invoke payment provider
            res = provider.initiate_payment(
                reference_id=idempotency_key,
                amount=payment.amount,
                currency=payment.currency,
                payer_info={"email": payer_user.email}
            )

            payment.provider_transaction_id = res['provider_transaction_id']
            payment.status = res['status']
            if res['status'] == PaymentStatus.SUCCEEDED:
                payment.confirmed_at = timezone.now()
                # Update settlement status to PAID (escrow state)
                settlement.status = SettlementStatus.PAID
                settlement.save()
                if settlement.invoice:
                    settlement.invoice.status = PaymentStatus.SUCCEEDED
                    settlement.invoice.paid_date = timezone.now()
                    settlement.invoice.save()

                # Schedule transporter payout
                PayoutService.schedule_payout(settlement)

            payment.save()

        return payment

    @classmethod

    def verify_and_confirm_payment(cls, payment: Payment, user) -> Payment:
        provider = MockPaymentProvider()
        res = provider.verify_payment(payment.provider_transaction_id or payment.idempotency_key)

        with transaction.atomic():
            if res['verified']:
                payment.status = PaymentStatus.SUCCEEDED
                payment.confirmed_at = timezone.now()
                payment.save()

                settlement = payment.settlement
                settlement.status = SettlementStatus.PAID
                settlement.save()

                PayoutService.schedule_payout(settlement)

        return payment


class ReconciliationService:
    """
    Domain service for financial reconciliation comparing internal payment records against provider status.
    """
    @classmethod

    def reconcile_payment(cls, payment: Payment) -> dict:
        provider = MockPaymentProvider()
        provider_status = provider.get_transaction_status(payment.provider_transaction_id)

        if not payment.provider_transaction_id:
            outcome = "MISSING_PROVIDER_TRANSACTION"
        elif payment.status == provider_status:
            outcome = "MATCHED"
        else:
            outcome = "STATUS_MISMATCH"

        return {
            "payment_id": payment.id,
            "idempotency_key": payment.idempotency_key,
            "internal_status": payment.status,
            "provider_status": provider_status,
            "reconciliation_outcome": outcome,
            "reconciled_at": timezone.now()
        }


class PayoutService:
    """
    Domain service for scheduling and processing transporter payouts.
    """
    @classmethod

    def schedule_payout(cls, settlement: FreightSettlement) -> TransporterPayout:
        if hasattr(settlement, 'payouts') and settlement.payouts.filter(status__in=[PayoutStatus.SCHEDULED, PayoutStatus.PAID]).exists():
            return settlement.payouts.filter(status__in=[PayoutStatus.SCHEDULED, PayoutStatus.PAID]).first()

        payout = TransporterPayout.objects.create(
            settlement=settlement,
            transporter=settlement.shipment.transporter,
            gross_amount=settlement.gross_freight_amount,
            commission_amount=settlement.platform_commission_amount,
            net_payout_amount=settlement.transporter_net_payable,
            status=PayoutStatus.SCHEDULED,
            payout_reference=f"PAYOUT-MOCK-{uuid.uuid4().hex[:6].upper()}",
            scheduled_at=timezone.now()
        )
        return payout

    @classmethod

    def process_payout(cls, payout: TransporterPayout, admin_user) -> TransporterPayout:
        if not (admin_user.is_superuser or admin_user.role == Role.ADMIN or admin_user.is_staff):
            raise PermissionDenied("Only administrators can process transporter payouts.")

        if payout.status == PayoutStatus.PAID:
            return payout

        with transaction.atomic():
            payout.status = PayoutStatus.PAID
            payout.processed_at = timezone.now()
            payout.save()

            settlement = payout.settlement
            settlement.status = SettlementStatus.SETTLED
            settlement.settled_at = timezone.now()
            settlement.save()

        return payout


class DisputeService:
    """
    Domain service managing payment settlement disputes.
    """
    @classmethod

    def raise_dispute(cls, settlement: FreightSettlement, user, reason: str, payment: Payment = None) -> PaymentDispute:
        is_shipper = hasattr(user, 'shipper_profile') and settlement.shipment.load.shipper == user.shipper_profile
        is_transporter = hasattr(user, 'transporter_profile') and settlement.shipment.transporter == user.transporter_profile
        is_admin = user.is_superuser or user.role == Role.ADMIN

        if not (is_shipper or is_transporter or is_admin):
            raise PermissionDenied("Only settlement participants or administrators can raise a dispute.")

        if not reason.strip():
            raise ValidationError({'reason': 'A reason is required to open a dispute.'})

        with transaction.atomic():
            dispute = PaymentDispute.objects.create(
                payment=payment,
                settlement=settlement,
                raised_by=user,
                reason=reason.strip(),
                status=PaymentDisputeStatus.OPEN
            )

            settlement.status = SettlementStatus.DISPUTED
            settlement.save()

        return dispute

    @classmethod

    def resolve_dispute(cls, dispute: PaymentDispute, admin_user, resolution_notes: str, new_status: str = PaymentDisputeStatus.RESOLVED) -> PaymentDispute:
        if not (admin_user.is_superuser or admin_user.role == Role.ADMIN or admin_user.is_staff):
            raise PermissionDenied("Only administrators can resolve financial disputes.")

        if not resolution_notes.strip():
            raise ValidationError({'resolution_notes': 'Resolution notes are required.'})

        with transaction.atomic():
            dispute.status = new_status
            dispute.resolution_notes = resolution_notes.strip()
            dispute.resolved_by = admin_user
            dispute.resolved_at = timezone.now()
            dispute.save()

            if new_status == PaymentDisputeStatus.RESOLVED:
                dispute.settlement.status = SettlementStatus.READY
                dispute.settlement.save()

        return dispute


# ============================================================================
# PHASE 9: OFFLINE-FIRST SYNCHRONIZATION SERVICES (SRS 2.4, 2.5, 4.1, 5.2)
# ============================================================================

class IncidentReportService:
    """
    Domain service for driver incident report creation.
    """
    @classmethod

    def create_incident_report(cls, shipment: Shipment, driver_user, incident_data: dict, offline_event: OfflineSyncEvent = None) -> DriverIncidentReport:
        is_transporter = hasattr(driver_user, 'transporter_profile') and shipment.transporter == driver_user.transporter_profile
        is_driver = hasattr(driver_user, 'driver_profile') and shipment.driver == driver_user.driver_profile
        is_admin = driver_user.is_superuser or driver_user.role == Role.ADMIN

        if not (is_transporter or is_driver or is_admin):
            raise PermissionDenied("Only assigned driver, transporter, or administrator can report an incident for this shipment.")

        driver_profile = getattr(driver_user, 'driver_profile', None)
        if not driver_profile and hasattr(shipment, 'driver'):
            driver_profile = shipment.driver

        if not driver_profile:
            # Fallback for admin or transporter reporting
            driver_profile = DriverProfile.objects.filter(transporter=shipment.transporter).first()

        reported_at = incident_data.get('reported_at') or timezone.now()

        report = DriverIncidentReport.objects.create(
            shipment=shipment,
            driver=driver_profile,
            reported_by=driver_user,
            incident_type=incident_data.get('incident_type', IncidentType.OTHER),
            latitude=incident_data.get('latitude'),
            longitude=incident_data.get('longitude'),
            location_name=incident_data.get('location_name', ''),
            description=incident_data.get('description', ''),
            reported_at=reported_at,
            offline_event=offline_event
        )

        # Log shipment milestone for incident visibility
        ShipmentMilestone.objects.create(
            shipment=shipment,
            status=shipment.status,
            location_name=report.location_name or shipment.origin,
            notes=f"INCIDENT REPORTED ({report.get_incident_type_display()}): {report.description}",
            updated_by=driver_user,
            timestamp=reported_at
        )

        try:
            from apps.marketplace.realtime_services import OperationalEventService
            from apps.marketplace.models import OperationalEventType, EventSeverity
            OperationalEventService.create_event(
                event_type=OperationalEventType.INCIDENT_REPORTED,
                severity=EventSeverity.HIGH,
                shipment=shipment,
                actor=driver_user,
                source='DRIVER_APP' if offline_event else 'LIVE_API',
                title=f"Driver Incident: {report.get_incident_type_display()}",
                description=report.description,
                payload={
                    "incident_id": report.id,
                    "incident_type": report.incident_type,
                    "location_name": report.location_name,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to emit OperationalEvent for incident #{report.id}: {str(e)}")

        return report



class OfflineSyncService:
    """
    Domain service executing batch offline synchronization, idempotency enforcement,
    per-event savepoints, timestamp preservation, and geographic validation.
    """
    MAX_BATCH_SIZE = 50

    @classmethod

    def process_batch(cls, user, events_data: list, device_id: str = "") -> dict:
        if len(events_data) > cls.MAX_BATCH_SIZE:
            raise ValidationError(f"Batch size ({len(events_data)}) exceeds maximum limit of {cls.MAX_BATCH_SIZE} events.")

        results = []
        synced_count = 0
        duplicate_count = 0
        failed_count = 0

        for event_dict in events_data:
            res = cls._process_single_event_safe(user, event_dict, device_id)
            results.append(res)
            if res['status'] == OfflineSyncStatus.SYNCED:
                synced_count += 1
            elif res['status'] == OfflineSyncStatus.DUPLICATE:
                duplicate_count += 1
            else:
                failed_count += 1

        return {
            "total_events": len(events_data),
            "synced_count": synced_count,
            "duplicate_count": duplicate_count,
            "failed_count": failed_count,
            "results": results
        }

    @classmethod

    def _process_single_event_safe(cls, user, event_dict: dict, device_id: str) -> dict:
        client_event_id = event_dict.get('client_event_id')
        if not client_event_id:
            return {
                "client_event_id": "UNKNOWN",
                "status": OfflineSyncStatus.REJECTED,
                "event_type": event_dict.get('event_type', 'UNKNOWN'),
                "server_record_id": None,
                "server_timestamp": timezone.now().isoformat(),
                "message": "Missing required field: client_event_id."
            }

        # Idempotency Check
        existing_event = OfflineSyncEvent.objects.filter(client_event_id=client_event_id).first()
        if existing_event:
            return {
                "client_event_id": client_event_id,
                "status": OfflineSyncStatus.DUPLICATE,
                "event_type": existing_event.event_type,
                "server_record_id": existing_event.server_record_id,
                "server_timestamp": existing_event.server_received_at.isoformat(),
                "message": "Event already synchronized (Idempotent request)."
            }

        sid = transaction.savepoint()
        try:
            res = cls._process_single_event_logic(user, event_dict, device_id)
            transaction.savepoint_commit(sid)
            return res
        except IntegrityError:
            transaction.savepoint_rollback(sid)
            existing_event = OfflineSyncEvent.objects.filter(client_event_id=client_event_id).first()
            if existing_event:
                return {
                    "client_event_id": client_event_id,
                    "status": OfflineSyncStatus.DUPLICATE,
                    "event_type": existing_event.event_type,
                    "server_record_id": existing_event.server_record_id,
                    "server_timestamp": existing_event.server_received_at.isoformat(),
                    "message": "Event already synchronized (Idempotent request)."
                }
            return {
                "client_event_id": client_event_id,
                "status": OfflineSyncStatus.DUPLICATE,
                "event_type": event_dict.get('event_type', 'UNKNOWN'),
                "server_record_id": None,
                "server_timestamp": timezone.now().isoformat(),
                "message": "Event already synchronized (Idempotent request)."
            }
        except Exception as e:
            transaction.savepoint_rollback(sid)
            err_msg = str(e)
            
            # Log failed sync record
            shipment_id = event_dict.get('shipment_id')
            shipment = Shipment.objects.filter(pk=shipment_id).first() if shipment_id else None
            
            if shipment:
                client_created_str = event_dict.get('client_created_at')
                client_dt = timezone.now()
                if client_created_str:
                    try:
                        client_dt = datetime.fromisoformat(client_created_str.replace('Z', '+00:00'))
                    except Exception:
                        pass
                
                try:
                    OfflineSyncEvent.objects.create(
                        client_event_id=client_event_id,
                        user=user,
                        device_id=device_id or event_dict.get('device_id', ''),
                        event_type=event_dict.get('event_type', OfflineSyncEventType.GPS_UPDATE),
                        shipment=shipment,
                        payload=event_dict.get('payload', {}),
                        client_created_at=client_dt,
                        status=OfflineSyncStatus.FAILED,
                        error_message=err_msg
                    )
                except IntegrityError:
                    pass

            return {
                "client_event_id": client_event_id,
                "status": OfflineSyncStatus.FAILED,
                "event_type": event_dict.get('event_type', 'UNKNOWN'),
                "server_record_id": None,
                "server_timestamp": timezone.now().isoformat(),
                "message": f"Processing failed: {err_msg}"
            }

    @classmethod

    def _process_single_event_logic(cls, user, event_dict: dict, device_id: str) -> dict:
        client_event_id = event_dict['client_event_id']
        event_type = event_dict.get('event_type')
        shipment_id = event_dict.get('shipment_id')
        client_created_str = event_dict.get('client_created_at')
        payload = event_dict.get('payload', {})

        if not event_type or event_type not in OfflineSyncEventType.values:
            raise ValidationError(f"Invalid or unsupported event_type '{event_type}'.")

        if not shipment_id:
            raise ValidationError("shipment_id is required for offline sync events.")

        try:
            shipment = Shipment.objects.get(pk=shipment_id)
        except Shipment.DoesNotExist:
            raise NotFound(f"Shipment #{shipment_id} not found.")

        # Authorization check
        is_transporter = hasattr(user, 'transporter_profile') and shipment.transporter == user.transporter_profile
        is_driver = hasattr(user, 'driver_profile') and shipment.driver == user.driver_profile
        is_admin = user.is_superuser or user.role == Role.ADMIN

        if not (is_transporter or is_driver or is_admin):
            raise PermissionDenied("You are not an assigned driver or participant on this shipment.")

        client_dt = timezone.now()
        if client_created_str:
            try:
                client_dt = datetime.fromisoformat(client_created_str.replace('Z', '+00:00'))
            except Exception:
                pass

        # Atomically claim client_event_id at database level before domain operations
        sync_event = OfflineSyncEvent.objects.create(
            client_event_id=client_event_id,
            user=user,
            device_id=device_id or event_dict.get('device_id', ''),
            event_type=event_type,
            shipment=shipment,
            payload=payload,
            client_created_at=client_dt,
            status=OfflineSyncStatus.SYNCED,
            processed_at=timezone.now()
        )

        server_record_id = None
        message = ""

        # Dispatch event type
        if event_type == OfflineSyncEventType.GPS_UPDATE:
            lat = payload.get('latitude')
            lon = payload.get('longitude')
            if lat is None or lon is None:
                raise ValidationError("GPS_UPDATE payload requires latitude and longitude.")

            location_update = TrackingService.record_location(
                shipment=shipment,
                latitude=float(lat),
                longitude=float(lon),
                speed_kmh=float(payload.get('speed_kmh')) if payload.get('speed_kmh') is not None else None,
                heading_degrees=float(payload.get('heading_degrees')) if payload.get('heading_degrees') is not None else None,
                location_name=payload.get('location_name', ''),
                user=user,
                timestamp=client_dt
            )
            server_record_id = location_update.id
            message = "GPS telemetry ping synchronized successfully."

        elif event_type == OfflineSyncEventType.WAYPOINT_CHECKIN:
            status_val = payload.get('status', ShipmentStatus.IN_TRANSIT)
            location_name = payload.get('location_name', '')
            notes = payload.get('notes', 'Offline waypoint check-in synced.')

            updated_shipment = TrackingService.update_status(
                shipment=shipment,
                new_status=status_val,
                user=user,
                location_name=location_name,
                notes=notes,
                timestamp=client_dt
            )
            milestone = updated_shipment.milestones.last()
            server_record_id = milestone.id if milestone else updated_shipment.id
            message = "Waypoint check-in milestone synchronized successfully."

        elif event_type == OfflineSyncEventType.INCIDENT_REPORT:
            report_data = {
                "incident_type": payload.get('incident_type', IncidentType.OTHER),
                "latitude": payload.get('latitude'),
                "longitude": payload.get('longitude'),
                "location_name": payload.get('location_name', ''),
                "description": payload.get('description', 'Offline driver incident report.'),
                "reported_at": client_dt
            }

            report = IncidentReportService.create_incident_report(
                shipment=shipment,
                driver_user=user,
                incident_data=report_data,
                offline_event=sync_event
            )
            server_record_id = report.id
            message = "Driver incident report synchronized successfully."

        sync_event.server_record_id = server_record_id
        sync_event.save(update_fields=['server_record_id'])

        return {
            "client_event_id": client_event_id,
            "status": OfflineSyncStatus.SYNCED,
            "event_type": event_type,
            "server_record_id": server_record_id,
            "server_timestamp": sync_event.server_received_at.isoformat(),
            "message": message
        }


# ============================================================================
# PHASE 10: ROUTE OPTIMIZATION, ETA & FUEL ANALYTICS SERVICES
# ============================================================================

class RouteOptimizationService:
    """
    Domain service executing Haversine distance calculations, route generation,
    ETA calculations, fuel consumption/cost estimation, deviation detection,
    and route recalculation logic.
    """
    DEFAULT_AVERAGE_SPEED_KMH = Decimal('50.00')
    DEFAULT_FUEL_EFFICIENCY_KM_PER_LITER = Decimal('3.50')
    DEFAULT_FUEL_PRICE_PER_LITER = Decimal('65.00')
    DEFAULT_DEVIATION_THRESHOLD_KM = Decimal('10.00')

    @classmethod
    def calculate_haversine_distance(cls, lat1, lon1, lat2, lon2) -> Decimal:
        """
        Calculates the great-circle distance between two points on the Earth
        using the Haversine formula. Returns distance in kilometers (Decimal).
        """
        try:
            lat1, lon1 = float(lat1), float(lon1)
            lat2, lon2 = float(lat2), float(lon2)
        except (ValueError, TypeError):
            raise ValidationError("Invalid numeric inputs for latitude and longitude coordinates.")

        if not (-90.0 <= lat1 <= 90.0 and -90.0 <= lat2 <= 90.0):
            raise ValidationError("Latitude coordinates must be between -90.0 and 90.0 degrees.")
        if not (-180.0 <= lon1 <= 180.0 and -180.0 <= lon2 <= 180.0):
            raise ValidationError("Longitude coordinates must be between -180.0 and 180.0 degrees.")

        # Earth radius in kilometers
        R = 6371.0

        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
             math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = R * c

        return Decimal(str(round(distance, 2)))

    @classmethod
    def create_route(cls, shipment: Shipment, waypoints_data: list, origin: str = "", destination: str = "", average_speed_kmh: Decimal = None) -> Route:
        if average_speed_kmh is None or average_speed_kmh <= 0:
            average_speed_kmh = cls.DEFAULT_AVERAGE_SPEED_KMH

        route_origin = origin or shipment.origin
        route_destination = destination or shipment.destination

        with transaction.atomic():
            # Deactivate previous active routes for this shipment
            Route.objects.filter(shipment=shipment, is_active=True).update(is_active=False, status=RouteStatus.SUPERSEDED)

            # Sort waypoints by sequence
            sorted_waypoints = sorted(waypoints_data, key=lambda w: w.get('sequence', 0))
            if len(sorted_waypoints) < 2:
                raise ValidationError("A route must contain at least 2 waypoints (origin and destination).")

            origin_wpt = sorted_waypoints[0]
            dest_wpt = sorted_waypoints[-1]

            route = Route.objects.create(
                shipment=shipment,
                is_active=True,
                origin=route_origin,
                origin_latitude=origin_wpt.get('latitude'),
                origin_longitude=origin_wpt.get('longitude'),
                destination=route_destination,
                destination_latitude=dest_wpt.get('latitude'),
                destination_longitude=dest_wpt.get('longitude'),
                status=RouteStatus.ACTIVE,
                average_speed_kmh=average_speed_kmh
            )

            total_distance = Decimal('0.00')
            total_duration_hours = Decimal('0.00')

            created_waypoints = []
            prev_wpt = None

            for wpt_dict in sorted_waypoints:
                sequence = wpt_dict['sequence']
                location_name = wpt_dict.get('location_name', f"Waypoint #{sequence}")
                lat = wpt_dict['latitude']
                lon = wpt_dict['longitude']

                dist_from_prev = Decimal('0.00')
                time_from_prev = Decimal('0.00')

                if prev_wpt is not None:
                    dist_from_prev = cls.calculate_haversine_distance(
                        prev_wpt['latitude'], prev_wpt['longitude'],
                        lat, lon
                    )
                    time_from_prev = Decimal(str(round(float(dist_from_prev) / float(average_speed_kmh), 2)))

                total_distance += dist_from_prev
                total_duration_hours += time_from_prev

                wpt_obj = RouteWaypoint.objects.create(
                    route=route,
                    sequence=sequence,
                    location_name=location_name,
                    latitude=lat,
                    longitude=lon,
                    expected_arrival_time=wpt_dict.get('expected_arrival_time'),
                    expected_departure_time=wpt_dict.get('expected_departure_time'),
                    distance_from_previous_km=dist_from_prev,
                    travel_time_from_previous_hours=time_from_prev
                )
                created_waypoints.append(wpt_obj)
                prev_wpt = wpt_dict

            route.total_distance_km = total_distance
            route.estimated_duration_hours = total_duration_hours
            route.estimated_arrival_time = timezone.now() + timedelta(hours=float(total_duration_hours))
            route.save(update_fields=['total_distance_km', 'estimated_duration_hours', 'estimated_arrival_time', 'updated_at'])

            return route

    @classmethod
    def recalculate_route(cls, shipment: Shipment, waypoints_data: list = None, reason: str = "Route recalculation requested", incident: DriverIncidentReport = None, triggered_by=None) -> RouteRecalculation:
        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        prev_distance = active_route.total_distance_km if active_route else Decimal('0.00')
        prev_eta = active_route.estimated_arrival_time if active_route else None

        with transaction.atomic():
            if not waypoints_data and active_route:
                # Re-evaluate current waypoints
                waypoints_data = [
                    {
                        "sequence": w.sequence,
                        "location_name": w.location_name,
                        "latitude": float(w.latitude),
                        "longitude": float(w.longitude),
                        "expected_arrival_time": w.expected_arrival_time,
                        "expected_departure_time": w.expected_departure_time,
                    }
                    for w in active_route.waypoints.all()
                ]
            elif not waypoints_data:
                raise ValidationError("Waypoints data required for route recalculation.")

            new_route = cls.create_route(
                shipment=shipment,
                waypoints_data=waypoints_data,
                average_speed_kmh=active_route.average_speed_kmh if active_route else cls.DEFAULT_AVERAGE_SPEED_KMH
            )

            recalc_audit = RouteRecalculation.objects.create(
                shipment=shipment,
                previous_route=active_route,
                new_route=new_route,
                triggered_by=triggered_by,
                incident=incident,
                reason=reason,
                previous_distance_km=prev_distance,
                new_distance_km=new_route.total_distance_km,
                previous_eta=prev_eta,
                new_eta=new_route.estimated_arrival_time
            )

            return recalc_audit

    @classmethod
    def calculate_actual_gps_distance(cls, shipment: Shipment) -> Decimal:
        location_updates = list(shipment.location_updates.order_by('timestamp'))
        if len(location_updates) < 2:
            return Decimal('0.00')

        total_actual_dist = Decimal('0.00')
        for i in range(len(location_updates) - 1):
            p1 = location_updates[i]
            p2 = location_updates[i+1]
            segment_dist = cls.calculate_haversine_distance(
                p1.latitude, p1.longitude,
                p2.latitude, p2.longitude
            )
            total_actual_dist += segment_dist

        return total_actual_dist

    @classmethod
    def detect_route_deviation(cls, shipment: Shipment, threshold_km: Decimal = None) -> dict:
        if threshold_km is None or threshold_km <= 0:
            threshold_km = cls.DEFAULT_DEVIATION_THRESHOLD_KM

        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        latest_gps = shipment.location_updates.order_by('-timestamp').first()

        if not active_route or not latest_gps:
            return {
                "shipment_id": shipment.id,
                "status": RouteDeviationStatus.UNKNOWN,
                "min_distance_to_route_km": None,
                "threshold_km": threshold_km,
                "message": "Insufficient active route or GPS telemetry data to evaluate deviation."
            }

        waypoints = list(active_route.waypoints.all())
        if not waypoints:
            return {
                "shipment_id": shipment.id,
                "status": RouteDeviationStatus.UNKNOWN,
                "min_distance_to_route_km": None,
                "threshold_km": threshold_km,
                "message": "Active route contains no waypoints."
            }

        min_dist = min([
            cls.calculate_haversine_distance(latest_gps.latitude, latest_gps.longitude, w.latitude, w.longitude)
            for w in waypoints
        ])

        deviation_status = RouteDeviationStatus.DEVIATED if min_dist > threshold_km else RouteDeviationStatus.ON_ROUTE

        return {
            "shipment_id": shipment.id,
            "status": deviation_status,
            "min_distance_to_route_km": min_dist,
            "threshold_km": threshold_km,
            "latest_gps_location": {
                "latitude": float(latest_gps.latitude),
                "longitude": float(latest_gps.longitude),
                "timestamp": latest_gps.timestamp.isoformat()
            },
            "message": f"Shipment is {deviation_status} (Distance to nearest waypoint: {min_dist} km)."
        }

    @classmethod
    def calculate_eta(cls, shipment: Shipment, average_speed_kmh: Decimal = None) -> dict:
        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        if not active_route:
            return {
                "shipment_id": shipment.id,
                "has_active_route": False,
                "estimated_arrival_time": None,
                "remaining_distance_km": Decimal('0.00'),
                "remaining_duration_hours": Decimal('0.00'),
                "message": "No active route found for shipment."
            }

        speed = average_speed_kmh or active_route.average_speed_kmh
        actual_traveled_km = cls.calculate_actual_gps_distance(shipment)

        total_planned_km = active_route.total_distance_km
        remaining_km = max(Decimal('0.00'), total_planned_km - actual_traveled_km)

        remaining_hours = Decimal('0.00')
        if speed > 0:
            remaining_hours = Decimal(str(round(float(remaining_km) / float(speed), 2)))

        eta_dt = timezone.now() + timedelta(hours=float(remaining_hours))

        return {
            "shipment_id": shipment.id,
            "has_active_route": True,
            "total_route_distance_km": total_planned_km,
            "traveled_distance_km": actual_traveled_km,
            "remaining_distance_km": remaining_km,
            "average_speed_kmh": speed,
            "remaining_duration_hours": remaining_hours,
            "estimated_arrival_time": eta_dt.isoformat(),
            "message": "Live ETA calculated based on progress."
        }

    @classmethod
    def calculate_fuel_analytics(cls, shipment: Shipment, fuel_efficiency_km_per_liter: Decimal = None, fuel_price_per_liter: Decimal = None) -> dict:
        efficiency = fuel_efficiency_km_per_liter or cls.DEFAULT_FUEL_EFFICIENCY_KM_PER_LITER
        price = fuel_price_per_liter or cls.DEFAULT_FUEL_PRICE_PER_LITER

        if efficiency <= 0:
            raise ValidationError("Fuel efficiency must be a positive number (km per liter).")
        if price <= 0:
            raise ValidationError("Fuel price must be a positive number.")

        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        planned_distance_km = active_route.total_distance_km if active_route else Decimal('0.00')
        actual_distance_km = cls.calculate_actual_gps_distance(shipment)

        planned_fuel_liters = Decimal(str(round(float(planned_distance_km) / float(efficiency), 2)))
        planned_fuel_cost_etb = Decimal(str(round(float(planned_fuel_liters) * float(price), 2)))

        actual_fuel_liters = Decimal(str(round(float(actual_distance_km) / float(efficiency), 2)))
        actual_fuel_cost_etb = Decimal(str(round(float(actual_fuel_liters) * float(price), 2)))

        return {
            "shipment_id": shipment.id,
            "fuel_efficiency_km_per_liter": efficiency,
            "fuel_price_per_liter_etb": price,
            "planned_distance_km": planned_distance_km,
            "planned_fuel_used_liters": planned_fuel_liters,
            "planned_fuel_cost_etb": planned_fuel_cost_etb,
            "actual_distance_km": actual_distance_km,
            "actual_fuel_used_liters": actual_fuel_liters,
            "actual_fuel_cost_etb": actual_fuel_cost_etb,
            "message": "Fuel consumption and cost analytics generated."
        }

    @classmethod
    def get_route_analytics(cls, shipment: Shipment) -> dict:
        active_route = Route.objects.filter(shipment=shipment, is_active=True).first()
        planned_distance = active_route.total_distance_km if active_route else Decimal('0.00')
        actual_distance = cls.calculate_actual_gps_distance(shipment)
        distance_variance = actual_distance - planned_distance

        planned_duration = active_route.estimated_duration_hours if active_route else Decimal('0.00')

        # Compute actual duration from first to last LocationUpdate
        first_gps = shipment.location_updates.order_by('timestamp').first()
        last_gps = shipment.location_updates.order_by('-timestamp').first()
        actual_duration = Decimal('0.00')
        if first_gps and last_gps and first_gps != last_gps:
            diff_seconds = (last_gps.timestamp - first_gps.timestamp).total_seconds()
            actual_duration = Decimal(str(round(diff_seconds / 3600.0, 2)))

        duration_variance = actual_duration - planned_duration

        fuel_data = cls.calculate_fuel_analytics(shipment)
        deviation_data = cls.detect_route_deviation(shipment)

        efficiency_pct = Decimal('100.00')
        if actual_distance > 0 and planned_distance > 0:
            efficiency_pct = Decimal(str(round((float(planned_distance) / float(actual_distance)) * 100.0, 2)))

        return {
            "shipment_id": shipment.id,
            "tracking_number": shipment.tracking_number,
            "has_active_route": active_route is not None,
            "planned_distance_km": planned_distance,
            "actual_distance_km": actual_distance,
            "distance_variance_km": distance_variance,
            "planned_duration_hours": planned_duration,
            "actual_duration_hours": actual_duration,
            "duration_variance_hours": duration_variance,
            "route_efficiency_percentage": efficiency_pct,
            "deviation_status": deviation_data['status'],
            "fuel_analytics": fuel_data,
            "recalculation_count": shipment.recalculations.count(),
            "incident_count": shipment.incident_reports.count()
        }
