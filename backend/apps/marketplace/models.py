from decimal import Decimal
from django.db import models
from django.conf import settings
from django.utils import timezone
from apps.accounts.models import TransporterProfile, DriverProfile, ShipperProfile


class VehicleType(models.TextChoices):
    CONTAINER_TRUCK = 'CONTAINER_TRUCK', 'Container Truck'
    FLATBED = 'FLATBED', 'Flatbed Trailer'
    REFRIGERATED = 'REFRIGERATED', 'Refrigerated Truck (Reefer)'
    TANKER = 'TANKER', 'Liquid Tanker'
    BULK_CARRIER = 'BULK_CARRIER', 'Dry Bulk Carrier'


class FuelType(models.TextChoices):
    DIESEL = 'DIESEL', 'Diesel'
    PETROL = 'PETROL', 'Petrol'
    ELECTRIC = 'ELECTRIC', 'Electric'
    HYBRID = 'HYBRID', 'Hybrid'


class Vehicle(models.Model):
    """
    Fleet vehicle registered by a Transporter for transport corridor execution.
    """
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.CASCADE,
        related_name='vehicles'
    )
    plate_number = models.CharField(
        max_length=50,
        unique=True,
        db_index=True
    )
    vehicle_type = models.CharField(
        max_length=30,
        choices=VehicleType.choices,
        default=VehicleType.FLATBED
    )
    capacity_tonnes = models.DecimalField(
        max_digits=8,
        decimal_places=2
    )
    fuel_type = models.CharField(
        max_length=20,
        choices=FuelType.choices,
        default=FuelType.DIESEL
    )
    insurance_policy_number = models.CharField(max_length=100, blank=True)
    insurance_expiration = models.DateField(null=True, blank=True)
    roadworthiness_certificate = models.CharField(max_length=100, blank=True)
    roadworthiness_expiration = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Fleet Vehicle'
        verbose_name_plural = 'Fleet Vehicles'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.plate_number} ({self.get_vehicle_type_display()} - {self.capacity_tonnes}T)"


class LoadStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    POSTED = 'POSTED', 'Posted on Spot Market'
    ASSIGNED = 'ASSIGNED', 'Assigned to Transporter'
    IN_TRANSIT = 'IN_TRANSIT', 'In Transit'
    DELIVERED = 'DELIVERED', 'Delivered'
    CANCELLED = 'CANCELLED', 'Cancelled'


class CargoLoad(models.Model):
    """
    Spot market cargo load posted by a Shipper for transport along Ethiopian trade corridors.
    """
    shipper = models.ForeignKey(
        ShipperProfile,
        on_delete=models.CASCADE,
        related_name='loads'
    )
    title = models.CharField(max_length=255)
    origin = models.CharField(max_length=255, db_index=True)
    destination = models.CharField(max_length=255, db_index=True)
    cargo_type = models.CharField(max_length=100)
    weight_tonnes = models.DecimalField(max_digits=8, decimal_places=2)
    volume_cubic_meters = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    required_vehicle_type = models.CharField(
        max_length=30,
        choices=VehicleType.choices,
        default=VehicleType.FLATBED
    )
    pickup_date = models.DateField()
    delivery_date = models.DateField()
    target_price = models.DecimalField(max_digits=12, decimal_places=2)
    special_instructions = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=LoadStatus.choices,
        default=LoadStatus.POSTED,
        db_index=True
    )
    assigned_transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_loads'
    )
    assigned_vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_loads'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Cargo Load'
        verbose_name_plural = 'Cargo Loads'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.origin} -> {self.destination})"


class BidStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', 'Submitted'
    ACCEPTED = 'ACCEPTED', 'Accepted'
    REJECTED = 'REJECTED', 'Rejected'
    WITHDRAWN = 'WITHDRAWN', 'Withdrawn'


class Bid(models.Model):
    """
    Competitive spot market bid submitted by a Transporter for a CargoLoad.
    """
    load = models.ForeignKey(
        CargoLoad,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.CASCADE,
        related_name='bids'
    )
    proposed_vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bids'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    estimated_pickup = models.DateField(null=True, blank=True)
    estimated_delivery = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=BidStatus.choices,
        default=BidStatus.SUBMITTED,
        db_index=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Spot Market Bid'
        verbose_name_plural = 'Spot Market Bids'
        ordering = ['-created_at']
        unique_together = ('load', 'transporter')

    def __str__(self):
        return f"Bid {self.amount} ETB by {self.transporter.company_name} on {self.load.title}"


# ============================================================================
# PHASE 6: SHIPMENT EXECUTION & REAL-TIME TRACKING MODELS
# ============================================================================

class ShipmentStatus(models.TextChoices):
    CREATED = 'CREATED', 'Shipment Initialized'
    DRIVER_ASSIGNED = 'DRIVER_ASSIGNED', 'Driver Assigned'
    AT_PICKUP = 'AT_PICKUP', 'Arrived at Pickup Location'
    IN_TRANSIT = 'IN_TRANSIT', 'In Transit Along Corridor'
    AT_DESTINATION = 'AT_DESTINATION', 'Arrived at Destination Port/Warehouse'
    DELIVERED = 'DELIVERED', 'Cargo Delivered'
    CANCELLED = 'CANCELLED', 'Shipment Cancelled'


class Shipment(models.Model):
    """
    Active shipment execution record tracking transport progress along Ethiopian corridors.
    """
    tracking_number = models.CharField(max_length=50, unique=True, db_index=True)
    load = models.OneToOneField(
        CargoLoad,
        on_delete=models.CASCADE,
        related_name='shipment'
    )
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.CASCADE,
        related_name='shipments'
    )
    vehicle = models.ForeignKey(
        Vehicle,
        on_delete=models.CASCADE,
        related_name='shipments'
    )
    driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipments'
    )
    status = models.CharField(
        max_length=30,
        choices=ShipmentStatus.choices,
        default=ShipmentStatus.CREATED,
        db_index=True
    )
    origin = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    actual_pickup_time = models.DateTimeField(null=True, blank=True)
    actual_delivery_time = models.DateTimeField(null=True, blank=True)
    estimated_arrival_at = models.DateTimeField(null=True, blank=True, db_index=True)
    eta_updated_at = models.DateTimeField(null=True, blank=True)
    eta_confidence = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    eta_basis = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shipment'
        verbose_name_plural = 'Shipments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'transporter']),
            models.Index(fields=['driver', 'status']),
        ]

    def __str__(self):
        return f"Shipment {self.tracking_number} ({self.status})"


class LocationUpdate(models.Model):
    """
    Real-time GPS telemetry location update ping recorded during shipment transit.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='location_updates'
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    speed_kmh = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    heading_degrees = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gps_updates'
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'Location Update'
        verbose_name_plural = 'Location Updates'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['shipment', '-timestamp']),
        ]

    def __str__(self):
        return f"GPS Ping for {self.shipment.tracking_number}: ({self.latitude}, {self.longitude}) at {self.timestamp}"


class ShipmentMilestone(models.Model):
    """
    Immutable audit log recording shipment status changes, timestamps, and notes.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='milestones'
    )
    status = models.CharField(
        max_length=30,
        choices=ShipmentStatus.choices
    )
    location_name = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='shipment_milestones'
    )
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = 'Shipment Milestone'
        verbose_name_plural = 'Shipment Milestones'
        ordering = ['timestamp']

    def __str__(self):
        return f"Milestone for {self.shipment.tracking_number}: {self.status} at {self.timestamp}"


# ============================================================================
# PHASE 7: DOCUMENT MANAGEMENT & DIGITAL PROOF OF DELIVERY (e-POD) MODELS
# ============================================================================

class DocumentType(models.TextChoices):
    WAYBILL = 'WAYBILL', 'Waybill / Bill of Lading'
    CUSTOMS_RELEASE = 'CUSTOMS_RELEASE', 'Customs Release Certificate'
    COMMERCIAL_INVOICE = 'COMMERCIAL_INVOICE', 'Commercial Invoice'
    PACKING_LIST = 'PACKING_LIST', 'Packing List'
    WEIGHT_BRIDGE_TICKET = 'WEIGHT_BRIDGE_TICKET', 'Weighbridge Ticket'
    PROOF_OF_DELIVERY_EVIDENCE = 'PROOF_OF_DELIVERY_EVIDENCE', 'Proof of Delivery Photo/Document'
    OTHER = 'OTHER', 'Other Transport Document'


class ShipmentDocument(models.Model):
    """
    Logistics transport document associated with an active shipment.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='documents'
    )
    document_type = models.CharField(
        max_length=40,
        choices=DocumentType.choices,
        default=DocumentType.WAYBILL,
        db_index=True
    )
    file = models.FileField(upload_to='shipment_documents/%Y/%m/')
    file_name = models.CharField(max_length=255)
    file_size_bytes = models.BigIntegerField()
    mime_type = models.CharField(max_length=100)
    checksum_sha256 = models.CharField(max_length=64, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_documents'
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shipment Document'
        verbose_name_plural = 'Shipment Documents'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shipment', 'document_type']),
        ]

    def __str__(self):
        return f"{self.get_document_type_display()} for {self.shipment.tracking_number}: {self.file_name}"


class CargoCondition(models.TextChoices):
    GOOD_CONDITION = 'GOOD_CONDITION', 'Good Condition (No Damage)'
    PARTIALLY_DAMAGED = 'PARTIALLY_DAMAGED', 'Partially Damaged'
    SEVERELY_DAMAGED = 'SEVERELY_DAMAGED', 'Severely Damaged'
    SHORTAGE_NOTED = 'SHORTAGE_NOTED', 'Quantity Shortage Noted'


class PODConfirmationStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', 'Submitted by Driver'
    CONFIRMED = 'CONFIRMED', 'Confirmed by Shipper'
    DISPUTED = 'DISPUTED', 'Disputed by Shipper'


class ProofOfDelivery(models.Model):
    """
    Digital Proof of Delivery (e-POD) captured upon cargo destination arrival.
    """
    shipment = models.OneToOneField(
        Shipment,
        on_delete=models.CASCADE,
        related_name='pod'
    )
    delivered_by_driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='delivered_pods'
    )
    recipient_name = models.CharField(max_length=255)
    recipient_phone = models.CharField(max_length=50)
    delivery_location = models.CharField(max_length=255)
    delivered_at = models.DateTimeField()
    signature_data = models.TextField(blank=True)
    cargo_condition = models.CharField(
        max_length=30,
        choices=CargoCondition.choices,
        default=CargoCondition.GOOD_CONDITION
    )
    received_weight_tonnes = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    delivery_notes = models.TextField(blank=True)
    confirmation_status = models.CharField(
        max_length=20,
        choices=PODConfirmationStatus.choices,
        default=PODConfirmationStatus.SUBMITTED,
        db_index=True
    )
    confirmed_by_shipper = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_pods'
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    dispute_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Proof of Delivery'
        verbose_name_plural = 'Proofs of Delivery'
        ordering = ['-created_at']

    def __str__(self):
        return f"e-POD for {self.shipment.tracking_number}: {self.confirmation_status} (Recipient: {self.recipient_name})"


# ============================================================================
# PHASE 8: PAYMENTS & FREIGHT SETTLEMENT MODELS (FR-10)
# ============================================================================

class PaymentStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    INITIATED = 'INITIATED', 'Payment Initiated'
    PROCESSING = 'PROCESSING', 'Processing'
    SUCCEEDED = 'SUCCEEDED', 'Payment Succeeded'
    FAILED = 'FAILED', 'Payment Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    REFUNDED = 'REFUNDED', 'Refunded'


class FreightInvoice(models.Model):
    """
    Freight invoice generated for a completed or assigned corridor shipment.
    """
    invoice_number = models.CharField(max_length=50, unique=True, db_index=True)
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='invoices'
    )
    issuer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='issued_invoices'
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payable_invoices'
    )
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='ETB')
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True
    )
    issue_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    paid_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Freight Invoice'
        verbose_name_plural = 'Freight Invoices'
        ordering = ['-created_at']

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.total_amount} {self.currency} ({self.status})"


class SettlementStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending e-POD'
    READY = 'READY', 'Ready for Payment'
    PAYMENT_PENDING = 'PAYMENT_PENDING', 'Payment Pending'
    PAID = 'PAID', 'Paid into Escrow State'
    SETTLED = 'SETTLED', 'Fully Settled'
    DISPUTED = 'DISPUTED', 'Disputed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class FreightSettlement(models.Model):
    """
    Financial reconciliation record for a freight shipment, calculating gross freight,
    platform commission, and transporter net payable amount.
    """
    shipment = models.OneToOneField(
        Shipment,
        on_delete=models.CASCADE,
        related_name='settlement'
    )
    invoice = models.ForeignKey(
        FreightInvoice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settlements'
    )
    gross_freight_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4, default=Decimal('0.0500'))
    platform_commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    transporter_net_payable = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=30,
        choices=SettlementStatus.choices,
        default=SettlementStatus.PENDING,
        db_index=True
    )
    settled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Freight Settlement'
        verbose_name_plural = 'Freight Settlements'
        ordering = ['-created_at']

    def __str__(self):
        return f"Settlement for {self.shipment.tracking_number}: {self.gross_freight_amount} ETB ({self.status})"


class Payment(models.Model):
    """
    Financial transaction record tracking payment initiation, verification, and status.
    Enforces idempotency reference key.
    """
    idempotency_key = models.CharField(max_length=100, unique=True, db_index=True)
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    settlement = models.ForeignKey(
        FreightSettlement,
        on_delete=models.CASCADE,
        related_name='payments'
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payments_made'
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default='ETB')
    provider = models.CharField(max_length=50, default='MOCK')
    provider_transaction_id = models.CharField(max_length=100, blank=True, db_index=True)
    payment_method = models.CharField(max_length=50, default='MOCK_TRANSFER')
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
        db_index=True
    )
    initiated_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payment Transaction'
        verbose_name_plural = 'Payment Transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.idempotency_key} - {self.amount} {self.currency} ({self.status})"


class PayoutStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Settlement'
    SCHEDULED = 'SCHEDULED', 'Payout Scheduled'
    PROCESSING = 'PROCESSING', 'Payout Processing'
    PAID = 'PAID', 'Payout Transferred'
    FAILED = 'FAILED', 'Payout Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class TransporterPayout(models.Model):
    """
    Net payout record scheduled and processed for a Transporter following settlement.
    """
    settlement = models.ForeignKey(
        FreightSettlement,
        on_delete=models.CASCADE,
        related_name='payouts'
    )
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.CASCADE,
        related_name='payouts'
    )
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    net_payout_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(
        max_length=20,
        choices=PayoutStatus.choices,
        default=PayoutStatus.PENDING,
        db_index=True
    )
    payout_reference = models.CharField(max_length=100, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Transporter Payout'
        verbose_name_plural = 'Transporter Payouts'
        ordering = ['-created_at']

    def __str__(self):
        return f"Payout {self.net_payout_amount} ETB to {self.transporter.company_name} ({self.status})"


class PaymentDisputeStatus(models.TextChoices):
    OPEN = 'OPEN', 'Dispute Open'
    UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
    RESOLVED = 'RESOLVED', 'Dispute Resolved'
    REJECTED = 'REJECTED', 'Dispute Rejected'
    CANCELLED = 'CANCELLED', 'Cancelled'


class PaymentDispute(models.Model):
    """
    Formal financial dispute raised regarding a payment transaction or settlement.
    """
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disputes'
    )
    settlement = models.ForeignKey(
        FreightSettlement,
        on_delete=models.CASCADE,
        related_name='disputes'
    )
    raised_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='disputes_raised'
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=PaymentDisputeStatus.choices,
        default=PaymentDisputeStatus.OPEN,
        db_index=True
    )
    resolution_notes = models.TextField(blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='disputes_resolved'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Payment Dispute'
        verbose_name_plural = 'Payment Disputes'
        ordering = ['-created_at']

    def __str__(self):
        return f"Dispute on Settlement #{self.settlement.id} by {self.raised_by.email} ({self.status})"


class Rating(models.Model):
    """
    Post-trip rating foundation between cargo shippers and transporters.
    """
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ratings_given'
    )
    ratee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ratings_received'
    )
    stars = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ratings'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Marketplace Rating'
        verbose_name_plural = 'Marketplace Ratings'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stars__gte=1) & models.Q(stars__lte=5),
                name='stars_range_1_to_5'
            )
        ]

    def __str__(self):
        return f"Rating: {self.stars} stars ({self.rater.email} -> {self.ratee.email})"


# ============================================================================
# PHASE 9: OFFLINE-FIRST SYNCHRONIZATION & INCIDENT REPORTING MODELS (SRS 2.4, 4.1, 5.2)
# ============================================================================

class OfflineSyncEventType(models.TextChoices):
    GPS_UPDATE = 'GPS_UPDATE', 'GPS Location Telemetry'
    WAYPOINT_CHECKIN = 'WAYPOINT_CHECKIN', 'Waypoint / Check-in Milestone'
    INCIDENT_REPORT = 'INCIDENT_REPORT', 'Driver Incident Report'


class OfflineSyncStatus(models.TextChoices):
    SYNCED = 'SYNCED', 'Synchronized Successfully'
    DUPLICATE = 'DUPLICATE', 'Duplicate Event (Idempotent)'
    REJECTED = 'REJECTED', 'Rejected (Validation / Auth Error)'
    CONFLICT = 'CONFLICT', 'Conflict (Superseded by Authoritative Event)'
    FAILED = 'FAILED', 'Processing Failed'


class OfflineSyncEvent(models.Model):
    """
    Offline synchronization log tracking mobile client event queueing, idempotency key deduplication,
    and server processing status.
    """
    client_event_id = models.CharField(max_length=100, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='offline_sync_events'
    )
    device_id = models.CharField(max_length=100, blank=True)
    event_type = models.CharField(
        max_length=30,
        choices=OfflineSyncEventType.choices,
        db_index=True
    )
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='offline_sync_events'
    )
    payload = models.JSONField()
    client_created_at = models.DateTimeField()
    server_received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=OfflineSyncStatus.choices,
        default=OfflineSyncStatus.SYNCED,
        db_index=True
    )
    retry_count = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)
    server_record_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Offline Sync Event'
        verbose_name_plural = 'Offline Sync Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'event_type']),
            models.Index(fields=['shipment', 'status']),
        ]

    def __str__(self):
        return f"Offline Event {self.client_event_id} ({self.event_type} - {self.status})"


class IncidentType(models.TextChoices):
    ACCIDENT = 'ACCIDENT', 'Traffic Accident'
    CHECKPOINT_DELAY = 'CHECKPOINT_DELAY', 'Customs / Police Checkpoint Delay'
    FUEL_UNAVAILABLE = 'FUEL_UNAVAILABLE', 'Fuel Shortage / Station Unavailable'
    ROAD_PROBLEM = 'ROAD_PROBLEM', 'Road Damage / Blockade'
    SECURITY_INCIDENT = 'SECURITY_INCIDENT', 'Security Threat / Armed Unrest'
    VEHICLE_BREAKDOWN = 'VEHICLE_BREAKDOWN', 'Mechanical Breakdown'
    OTHER = 'OTHER', 'Other Incident'


class DriverIncidentReport(models.Model):
    """
    Driver incident report recorded during corridor transport (queued offline or submitted live).
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='incident_reports'
    )
    driver = models.ForeignKey(
        DriverProfile,
        on_delete=models.CASCADE,
        related_name='incident_reports'
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='incident_reports_submitted'
    )
    incident_type = models.CharField(
        max_length=30,
        choices=IncidentType.choices,
        default=IncidentType.OTHER,
        db_index=True
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    description = models.TextField()
    reported_at = models.DateTimeField()
    offline_event = models.ForeignKey(
        OfflineSyncEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='incident_reports'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Driver Incident Report'
        verbose_name_plural = 'Driver Incident Reports'
        ordering = ['-reported_at']

    def __str__(self):
        return f"Incident Report ({self.incident_type}) for {self.shipment.tracking_number} by Driver {self.driver.user.get_full_name()}"


# ============================================================================
# PHASE 10: ROUTE OPTIMIZATION, ETA & FUEL ANALYTICS MODELS
# ============================================================================

class RouteStatus(models.TextChoices):
    PLANNED = 'PLANNED', 'Planned'
    ACTIVE = 'ACTIVE', 'Active'
    COMPLETED = 'COMPLETED', 'Completed'
    CANCELLED = 'CANCELLED', 'Cancelled'
    RECALCULATING = 'RECALCULATING', 'Recalculating'
    SUPERSEDED = 'SUPERSEDED', 'Superseded'


class RouteDeviationStatus(models.TextChoices):
    ON_ROUTE = 'ON_ROUTE', 'On Route'
    DEVIATED = 'DEVIATED', 'Deviated'
    UNKNOWN = 'UNKNOWN', 'Unknown'


class Route(models.Model):
    """
    Intelligent shipment route representation storing origin/destination coordinates,
    total distance, estimated travel time, and route status.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='routes'
    )
    is_active = models.BooleanField(default=True, db_index=True)
    origin = models.CharField(max_length=255)
    origin_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    origin_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination = models.CharField(max_length=255)
    destination_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    destination_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    total_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    estimated_duration_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    estimated_arrival_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=RouteStatus.choices,
        default=RouteStatus.PLANNED,
        db_index=True
    )
    average_speed_kmh = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('50.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Shipment Route'
        verbose_name_plural = 'Shipment Routes'
        ordering = ['-created_at']

    def __str__(self):
        return f"Route for {self.shipment.tracking_number}: {self.origin} -> {self.destination} ({self.total_distance_km} km)"


class RouteWaypoint(models.Model):
    """
    Ordered waypoint representation for a planned or active shipment route.
    """
    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name='waypoints'
    )
    sequence = models.PositiveIntegerField(db_index=True)
    location_name = models.CharField(max_length=255)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    expected_arrival_time = models.DateTimeField(null=True, blank=True)
    expected_departure_time = models.DateTimeField(null=True, blank=True)
    distance_from_previous_km = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    travel_time_from_previous_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))

    class Meta:
        verbose_name = 'Route Waypoint'
        verbose_name_plural = 'Route Waypoints'
        ordering = ['sequence']
        unique_together = ('route', 'sequence')

    def __str__(self):
        return f"Waypoint #{self.sequence} ({self.location_name}) for Route #{self.route_id}"


class RouteRecalculation(models.Model):
    """
    Audit record capturing route recalculation events triggered by incidents or deviations.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='recalculations'
    )
    previous_route = models.ForeignKey(
        Route,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='superseded_by'
    )
    new_route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name='recalculation_results'
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='route_recalculations_initiated'
    )
    incident = models.ForeignKey(
        DriverIncidentReport,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='route_recalculations'
    )
    reason = models.TextField()
    previous_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    new_distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    previous_eta = models.DateTimeField(null=True, blank=True)
    new_eta = models.DateTimeField(null=True, blank=True)
    recalculated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Route Recalculation Audit'
        verbose_name_plural = 'Route Recalculation Audits'
        ordering = ['-recalculated_at']

    def __str__(self):
        return f"Recalculation for Shipment {self.shipment.tracking_number} at {self.recalculated_at}"


# ============================================================================
# PHASE 11: AI PREDICTIVE LOGISTICS & RISK INTELLIGENCE MODELS
# ============================================================================

class PredictionType(models.TextChoices):
    ETA_DELAY = 'ETA_DELAY', 'ETA Delay Prediction'
    SHIPMENT_RISK = 'SHIPMENT_RISK', 'Shipment Delay Risk'
    ROUTE_RISK = 'ROUTE_RISK', 'Route Risk'
    FUEL_CONSUMPTION = 'FUEL_CONSUMPTION', 'Fuel Consumption Prediction'
    INCIDENT_RISK = 'INCIDENT_RISK', 'Incident Risk'
    OPERATIONAL_RISK = 'OPERATIONAL_RISK', 'Aggregate Operational Risk'


class RiskLevel(models.TextChoices):
    LOW = 'LOW', 'Low Risk'
    MEDIUM = 'MEDIUM', 'Medium Risk'
    HIGH = 'HIGH', 'High Risk'
    CRITICAL = 'CRITICAL', 'Critical Risk'

    @classmethod
    def from_score(cls, score: int) -> 'RiskLevel':
        """
        Derives deterministic RiskLevel from numeric risk score (0 to 100).
        0–24: LOW
        25–49: MEDIUM
        50–74: HIGH
        75–100: CRITICAL
        """
        score = max(0, min(100, int(score)))
        if score <= 24:
            return cls.LOW
        elif score <= 49:
            return cls.MEDIUM
        elif score <= 74:
            return cls.HIGH
        else:
            return cls.CRITICAL


class PredictiveModel(models.Model):
    """
    Registry tracking predictive models and algorithms used to generate risk predictions.
    """
    name = models.CharField(max_length=100)
    model_type = models.CharField(max_length=50, choices=PredictionType.choices)
    version = models.CharField(max_length=50, default='1.0')
    algorithm = models.CharField(max_length=100, default='Deterministic Weighted Heuristic')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    trained_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Predictive Model'
        verbose_name_plural = 'Predictive Models'
        ordering = ['-created_at']
        unique_together = ('name', 'version')

    def __str__(self):
        return f"{self.name} v{self.version} ({self.get_model_type_display()})"


class PredictionRecord(models.Model):
    """
    Auditable persistent record of a generated logistics prediction.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='predictions'
    )
    route = models.ForeignKey(
        Route,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='predictions'
    )
    prediction_model = models.ForeignKey(
        PredictiveModel,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='predictions'
    )
    prediction_type = models.CharField(max_length=50, choices=PredictionType.choices)
    prediction_value = models.JSONField(default=dict)
    risk_score = models.IntegerField(default=0)
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW)
    confidence_score = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.80'))
    prediction_horizon_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('24.00'))
    input_features = models.JSONField(default=dict)
    explanation = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Prediction Record'
        verbose_name_plural = 'Prediction Records'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shipment', 'prediction_type', '-created_at']),
            models.Index(fields=['risk_level']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.get_prediction_type_display()} for {self.shipment.tracking_number}: {self.risk_level} ({self.risk_score})"


# ============================================================================
# PHASE 12: DYNAMIC PRICING & FREIGHT MARKET INTELLIGENCE MODELS
# ============================================================================

class MarketPressure(models.TextChoices):
    LOW = 'LOW', 'Low Demand Pressure (Abundant Transporters / Low Load Volume)'
    NORMAL = 'NORMAL', 'Normal Balanced Market Conditions'
    HIGH = 'HIGH', 'High Demand Pressure (High Load Volume / Transporter Scarcity)'


class PricingStrategy(models.Model):
    """
    Configurable pricing strategy parameters and factor weighting rules for freight calculations.
    """
    name = models.CharField(max_length=100)
    version = models.CharField(max_length=20, default='1.0')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True, db_index=True)

    base_rate_per_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('50.00'))
    minimum_rate_per_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('35.00'))
    maximum_rate_per_km = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('120.00'))

    fuel_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    distance_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    risk_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    incident_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    route_deviation_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    market_demand_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    market_supply_weight = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Pricing Strategy'
        verbose_name_plural = 'Pricing Strategies'
        unique_together = ('name', 'version')
        ordering = ['-is_active', 'name', 'version']
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['name', 'version']),
        ]

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.name} v{self.version} ({status})"


class PriceRecommendation(models.Model):
    """
    Auditable persistent record of generated freight price recommendations for decision support.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='price_recommendations',
        db_index=True
    )
    pricing_strategy = models.ForeignKey(
        PricingStrategy,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recommendations'
    )
    recommended_price_etb = models.DecimalField(max_digits=12, decimal_places=2)
    minimum_price_etb = models.DecimalField(max_digits=12, decimal_places=2)
    maximum_price_etb = models.DecimalField(max_digits=12, decimal_places=2)

    base_price_etb = models.DecimalField(max_digits=12, decimal_places=2)
    distance_adjustment_etb = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    fuel_adjustment_etb = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    risk_adjustment_etb = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    market_adjustment_etb = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    pricing_confidence_score = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('0.85'))
    market_pressure = models.CharField(max_length=20, choices=MarketPressure.choices, default=MarketPressure.NORMAL, db_index=True)
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.LOW, db_index=True)

    factors = models.JSONField(default=list, help_text="Structured list of pricing breakdown factors with ETB impact and description.")
    calculation_snapshot = models.JSONField(default=dict, help_text="Audit snapshot of exact input features (distance, fuel cost, risk score, market pressure).")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Price Recommendation'
        verbose_name_plural = 'Price Recommendations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shipment', '-created_at']),
            models.Index(fields=['market_pressure']),
            models.Index(fields=['risk_level']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Recommendation {self.recommended_price_etb} ETB for {self.shipment.tracking_number} ({self.market_pressure})"


class PricingMarketSnapshot(models.Model):
    """
    Internal market condition snapshot aggregated from database metrics along transport corridors.
    """
    origin_region = models.CharField(max_length=100, db_index=True)
    destination_region = models.CharField(max_length=100, db_index=True)

    active_load_count = models.IntegerField(default=0)
    active_bid_count = models.IntegerField(default=0)
    available_transporter_count = models.IntegerField(default=0)

    average_historical_price_etb = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    average_price_per_km = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    demand_score = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('50.00'))
    supply_score = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('50.00'))
    market_pressure = models.CharField(max_length=20, choices=MarketPressure.choices, default=MarketPressure.NORMAL)

    snapshot_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Pricing Market Snapshot'
        verbose_name_plural = 'Pricing Market Snapshots'
        ordering = ['-snapshot_at']
        indexes = [
            models.Index(fields=['origin_region', 'destination_region', '-snapshot_at']),
            models.Index(fields=['snapshot_at']),
        ]

    def __str__(self):
        return f"Market Snapshot {self.origin_region} -> {self.destination_region} ({self.market_pressure})"


# ============================================================================
# PHASE 13 — AUTOMATED WORKFLOW & SMART OPERATIONS ENUMS & MODELS
# ============================================================================

class RecommendationPriority(models.TextChoices):
    LOW = 'LOW', 'Low'
    MEDIUM = 'MEDIUM', 'Medium'
    HIGH = 'HIGH', 'High'
    CRITICAL = 'CRITICAL', 'Critical'


class RecommendationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    EXECUTED = 'EXECUTED', 'Executed'
    FAILED = 'FAILED', 'Failed'


class AutomationRuleType(models.TextChoices):
    HIGH_OPERATIONAL_RISK = 'HIGH_OPERATIONAL_RISK', 'High Operational Risk'
    ROUTE_DEVIATION = 'ROUTE_DEVIATION', 'Route Deviation Detected'
    HIGH_ETA_DELAY = 'HIGH_ETA_DELAY', 'High ETA Delay Predicted'
    INCIDENT_REPORTED = 'INCIDENT_REPORTED', 'Driver Incident Reported'
    HIGH_FUEL_RISK = 'HIGH_FUEL_RISK', 'High Fuel Consumption/Cost'
    HIGH_MARKET_PRESSURE = 'HIGH_MARKET_PRESSURE', 'High Corridor Market Pressure'
    STALE_GPS_DATA = 'STALE_GPS_DATA', 'Stale GPS Telemetry'


class AutomationRecommendationType(models.TextChoices):
    REVIEW_SHIPMENT = 'REVIEW_SHIPMENT', 'Review Shipment Operations'
    REVIEW_ROUTE = 'REVIEW_ROUTE', 'Review Planned Route'
    RECALCULATE_ROUTE = 'RECALCULATE_ROUTE', 'Recalculate Route'
    CONTACT_DRIVER = 'CONTACT_DRIVER', 'Contact Assigned Driver'
    REVIEW_INCIDENT = 'REVIEW_INCIDENT', 'Review Reported Incident'
    REVIEW_PRICING = 'REVIEW_PRICING', 'Review Freight Market Pricing'
    ESCALATE_TO_ADMIN = 'ESCALATE_TO_ADMIN', 'Escalate to Platform Admin'


class AutomationRule(models.Model):
    """
    Configurable operational automation detection rule.
    """
    name = models.CharField(max_length=150, unique=True, help_text="Unique descriptive name for the rule.")
    rule_type = models.CharField(max_length=50, choices=AutomationRuleType.choices, db_index=True)
    description = models.TextField(blank=True, help_text="Human-readable description of rule conditions.")

    is_active = models.BooleanField(default=True, db_index=True)
    priority = models.CharField(max_length=20, choices=RecommendationPriority.choices, default=RecommendationPriority.MEDIUM)
    configuration = models.JSONField(default=dict, help_text="Configurable rule parameters and threshold metrics.")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Automation Rule'
        verbose_name_plural = 'Automation Rules'
        ordering = ['name']

    def __str__(self):
        return f"Rule: {self.name} ({self.rule_type})"


class AutomationRecommendation(models.Model):
    """
    Generated decision-support workflow recommendation requiring explicit user authorization.
    """
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name='automation_recommendations', db_index=True)
    rule = models.ForeignKey(AutomationRule, on_delete=models.SET_NULL, null=True, blank=True, related_name='recommendations')

    recommendation_type = models.CharField(max_length=50, choices=AutomationRecommendationType.choices, db_index=True)
    priority = models.CharField(max_length=20, choices=RecommendationPriority.choices, default=RecommendationPriority.MEDIUM, db_index=True)
    status = models.CharField(max_length=20, choices=RecommendationStatus.choices, default=RecommendationStatus.PENDING, db_index=True)

    title = models.CharField(max_length=200)
    description = models.TextField()
    recommended_action = models.CharField(max_length=200)

    context_snapshot = models.JSONField(default=dict, help_text="Immutable operational evidence snapshot at evaluation time.")

    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_recommendations')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, help_text="Reason provided when recommendation is rejected.")

    execution_result = models.JSONField(default=dict, blank=True, help_text="Audit details produced upon successful execution.")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Automation Recommendation'
        verbose_name_plural = 'Automation Recommendations'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shipment', 'status']),
            models.Index(fields=['shipment', 'rule', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"[{self.status}] {self.title} for Shipment {self.shipment.tracking_number}"


class AutomationExecution(models.Model):
    """
    Immutable execution audit history for approved workflow recommendations.
    """
    recommendation = models.ForeignKey(AutomationRecommendation, on_delete=models.CASCADE, related_name='executions')
    executed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='executed_automation_actions')

    action_type = models.CharField(max_length=50)
    status = models.CharField(max_length=20, default='SUCCESS')
    result = models.JSONField(default=dict)

    executed_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Automation Execution'
        verbose_name_plural = 'Automation Executions'
        ordering = ['-executed_at']
        indexes = [
            models.Index(fields=['recommendation', '-executed_at']),
            models.Index(fields=['executed_at']),
        ]

    def __str__(self):
        return f"Execution {self.action_type} on Rec #{self.recommendation_id} by {self.executed_by}"


# ============================================================================
# PHASE 14: REAL-TIME OPERATIONS, NOTIFICATIONS & EVENT INTELLIGENCE
# ============================================================================

class OperationalEventType(models.TextChoices):
    ROUTE_DEVIATION = 'ROUTE_DEVIATION', 'Route Deviation Detected'
    ETA_DELAY = 'ETA_DELAY', 'ETA Arrival Delay Predicted'
    HIGH_OPERATIONAL_RISK = 'HIGH_OPERATIONAL_RISK', 'High Operational Risk Level'
    INCIDENT_REPORTED = 'INCIDENT_REPORTED', 'Driver Incident Reported'
    FUEL_RISK = 'FUEL_RISK', 'High Fuel Consumption Risk'
    HIGH_MARKET_PRESSURE = 'HIGH_MARKET_PRESSURE', 'High Corridor Market Pressure'
    STALE_GPS = 'STALE_GPS', 'Stale GPS Telemetry Ping'
    AUTOMATION_RECOMMENDATION = 'AUTOMATION_RECOMMENDATION', 'Workflow Recommendation Created'
    AUTOMATION_APPROVAL_REQUIRED = 'AUTOMATION_APPROVAL_REQUIRED', 'Workflow Recommendation Requires Approval'
    AUTOMATION_EXECUTED = 'AUTOMATION_EXECUTED', 'Workflow Recommendation Executed'
    SHIPMENT_STATUS_CHANGED = 'SHIPMENT_STATUS_CHANGED', 'Shipment Status Transition'
    PAYMENT_EVENT = 'PAYMENT_EVENT', 'Freight Settlement / Payment Event'
    SYSTEM_ALERT = 'SYSTEM_ALERT', 'System Operational Alert'


class EventSeverity(models.TextChoices):
    LOW = 'LOW', 'Low Severity'
    MEDIUM = 'MEDIUM', 'Medium Severity'
    HIGH = 'HIGH', 'High Severity'
    CRITICAL = 'CRITICAL', 'Critical Severity'


class NotificationType(models.TextChoices):
    OPERATIONAL_ALERT = 'OPERATIONAL_ALERT', 'Operational Alert'
    SHIPMENT_UPDATE = 'SHIPMENT_UPDATE', 'Shipment Update'
    ROUTE_ALERT = 'ROUTE_ALERT', 'Route Corridor Alert'
    ETA_ALERT = 'ETA_ALERT', 'ETA Delay Alert'
    RISK_ALERT = 'RISK_ALERT', 'Risk Level Alert'
    INCIDENT_ALERT = 'INCIDENT_ALERT', 'Driver Incident Alert'
    FUEL_ALERT = 'FUEL_ALERT', 'Fuel Consumption Alert'
    MARKET_ALERT = 'MARKET_ALERT', 'Corridor Market Alert'
    AUTOMATION_ALERT = 'AUTOMATION_ALERT', 'Workflow Automation Alert'
    SYSTEM_ALERT = 'SYSTEM_ALERT', 'System Operational Alert'


class OperationalEvent(models.Model):
    """
    Immutable operational event record capturing critical platform activities.
    """
    event_type = models.CharField(max_length=50, choices=OperationalEventType.choices, db_index=True)
    severity = models.CharField(max_length=20, choices=EventSeverity.choices, default=EventSeverity.MEDIUM, db_index=True)
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, null=True, blank=True, related_name='operational_events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='acted_operational_events')

    source = models.CharField(max_length=100, default='SYSTEM')
    title = models.CharField(max_length=255)
    description = models.TextField()
    payload = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=255, unique=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Operational Event'
        verbose_name_plural = 'Operational Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['shipment', '-created_at']),
            models.Index(fields=['event_type', 'severity']),
            models.Index(fields=['created_at']),
            models.Index(fields=['idempotency_key']),
        ]

    def __str__(self):
        return f"[{self.severity}] {self.event_type}: {self.title}"


class Notification(models.Model):
    """
    Persistent notification entity generated for authorized recipients.
    """
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    event = models.ForeignKey(OperationalEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications')
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, null=True, blank=True, related_name='notifications')

    notification_type = models.CharField(max_length=50, choices=NotificationType.choices, db_index=True)
    priority = models.CharField(max_length=20, choices=EventSeverity.choices, default=EventSeverity.MEDIUM, db_index=True)

    title = models.CharField(max_length=255)
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)

    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    is_acknowledged = models.BooleanField(default=False, db_index=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['event', 'recipient'], condition=models.Q(event__isnull=False), name='unique_event_recipient_notification')
        ]
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['shipment', '-created_at']),
            models.Index(fields=['priority']),
        ]

    def __str__(self):
        return f"Notification for {self.recipient.email}: {self.title} (Read: {self.is_read})"


class NotificationPreference(models.Model):
    """
    Per-user notification delivery and alert filtering preferences.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preferences')

    route_alerts_enabled = models.BooleanField(default=True)
    eta_alerts_enabled = models.BooleanField(default=True)
    risk_alerts_enabled = models.BooleanField(default=True)
    incident_alerts_enabled = models.BooleanField(default=True)
    fuel_alerts_enabled = models.BooleanField(default=True)
    market_alerts_enabled = models.BooleanField(default=True)
    automation_alerts_enabled = models.BooleanField(default=True)
    shipment_updates_enabled = models.BooleanField(default=True)
    system_alerts_enabled = models.BooleanField(default=True)
    critical_alerts_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Notification Preference'
        verbose_name_plural = 'Notification Preferences'

    def __str__(self):
        return f"Preferences for {self.user.email}"


# ============================================================================
# PHASE 18: EXTERNAL INTEGRATIONS, WEBHOOKS & ENTERPRISE DATA EXCHANGE MODELS
# ============================================================================

class IntegrationType(models.TextChoices):
    ERP = 'ERP', 'Enterprise Resource Planning'
    ACCOUNTING = 'ACCOUNTING', 'Accounting & Financial System'
    LOGISTICS = 'LOGISTICS', 'Logistics Platform'
    TRACKING = 'TRACKING', 'Telematics & Tracking Service'
    ANALYTICS = 'ANALYTICS', 'Enterprise Analytics System'
    CUSTOM = 'CUSTOM', 'Custom Webhook Integration'


class IntegrationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    INACTIVE = 'INACTIVE', 'Inactive'
    DISABLED = 'DISABLED', 'Disabled by System'
    ERROR = 'ERROR', 'Error / Connection Failed'


class ExternalIntegration(models.Model):
    """
    Configured connection between TradeFlow and an external enterprise system.
    """
    name = models.CharField(max_length=255)
    integration_type = models.CharField(max_length=30, choices=IntegrationType.choices, default=IntegrationType.CUSTOM, db_index=True)
    status = models.CharField(max_length=20, choices=IntegrationStatus.choices, default=IntegrationStatus.ACTIVE, db_index=True)
    base_url = models.URLField(max_length=500, blank=True)
    webhook_secret = models.CharField(max_length=255, blank=True)
    api_key_reference = models.CharField(max_length=255, blank=True)
    configuration = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_integrations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'External Integration'
        verbose_name_plural = 'External Integrations'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.integration_type}) - {self.status}"


class WebhookEndpoint(models.Model):
    """
    Configured HTTP URL endpoint for publishing TradeFlow operational events.
    """
    integration = models.ForeignKey(
        ExternalIntegration,
        on_delete=models.CASCADE,
        related_name='webhook_endpoints'
    )
    name = models.CharField(max_length=255)
    url = models.URLField(max_length=500)
    event_types = models.JSONField(default=list, help_text="List of subscribed event type strings")
    is_active = models.BooleanField(default=True, db_index=True)
    secret = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Webhook Endpoint'
        verbose_name_plural = 'Webhook Endpoints'
        ordering = ['-created_at']

    def __str__(self):
        return f"Webhook '{self.name}' ({self.integration.name}) -> {self.url}"


class WebhookDeliveryStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Delivery'
    PROCESSING = 'PROCESSING', 'Processing HTTP Request'
    DELIVERED = 'DELIVERED', 'Delivered Successfully'
    FAILED = 'FAILED', 'Delivery Failed'
    RETRYING = 'RETRYING', 'Retrying Delivery'
    CANCELLED = 'CANCELLED', 'Cancelled'


class WebhookDelivery(models.Model):
    """
    Record of outbound HTTP event delivery attempt to an external webhook endpoint.
    """
    webhook_endpoint = models.ForeignKey(
        WebhookEndpoint,
        on_delete=models.CASCADE,
        related_name='deliveries'
    )
    event_type = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=255, db_index=True)

    status = models.CharField(max_length=20, choices=WebhookDeliveryStatus.choices, default=WebhookDeliveryStatus.PENDING, db_index=True)

    attempt_count = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)

    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)

    response_status = models.PositiveIntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, help_text="Truncated response body (max 2000 chars)")

    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Webhook Delivery'
        verbose_name_plural = 'Webhook Deliveries'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['webhook_endpoint', 'idempotency_key'],
                name='unique_endpoint_idempotency_delivery'
            )
        ]
        indexes = [
            models.Index(fields=['webhook_endpoint', 'status']),
            models.Index(fields=['status', 'next_retry_at']),
        ]

    def __str__(self):
        return f"Delivery #{self.id} ({self.event_type}) -> {self.status} (Attempts: {self.attempt_count}/{self.max_attempts})"


class InboundWebhookStatus(models.TextChoices):
    RECEIVED = 'RECEIVED', 'Received'
    PROCESSING = 'PROCESSING', 'Processing'
    PROCESSED = 'PROCESSED', 'Processed Successfully'
    FAILED = 'FAILED', 'Processing Failed'
    REJECTED = 'REJECTED', 'Signature / Format Rejected'
    DUPLICATE = 'DUPLICATE', 'Duplicate Event Ignored'


class InboundWebhookEvent(models.Model):
    """
    Log of inbound webhook events received from external enterprise systems.
    """
    integration = models.ForeignKey(
        ExternalIntegration,
        on_delete=models.CASCADE,
        related_name='inbound_events'
    )
    event_type = models.CharField(max_length=100, db_index=True)
    external_event_id = models.CharField(max_length=255, db_index=True)

    payload = models.JSONField(default=dict)

    signature_valid = models.BooleanField(default=False)
    processing_status = models.CharField(max_length=20, choices=InboundWebhookStatus.choices, default=InboundWebhookStatus.RECEIVED, db_index=True)

    idempotency_key = models.CharField(max_length=255, db_index=True)

    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Inbound Webhook Event'
        verbose_name_plural = 'Inbound Webhook Events'
        ordering = ['-received_at']
        constraints = [
            models.UniqueConstraint(
                fields=['integration', 'external_event_id'],
                name='unique_integration_external_event'
            )
        ]

    def __str__(self):
        return f"Inbound #{self.id} ({self.event_type}) from {self.integration.name} -> {self.processing_status}"


# ============================================================================
# PHASE 19: ADVANCED SECURITY, COMPLIANCE & GOVERNANCE MODELS
# ============================================================================

class SecurityAuditEventSeverity(models.TextChoices):
    INFO = 'INFO', 'Informational'
    LOW = 'LOW', 'Low Severity'
    MEDIUM = 'MEDIUM', 'Medium Severity'
    HIGH = 'HIGH', 'High Severity'
    CRITICAL = 'CRITICAL', 'Critical Severity'


class SecurityAuditEventType(models.TextChoices):
    LOGIN_SUCCESS = 'LOGIN_SUCCESS', 'Successful Login'
    LOGIN_FAILURE = 'LOGIN_FAILURE', 'Failed Login Attempt'
    LOGOUT = 'LOGOUT', 'User Logout'
    TOKEN_REFRESH = 'TOKEN_REFRESH', 'JWT Token Refresh'
    TOKEN_REVOKED = 'TOKEN_REVOKED', 'JWT Token Revoked'
    PASSWORD_CHANGED = 'PASSWORD_CHANGED', 'Password Changed'
    PASSWORD_RESET_REQUESTED = 'PASSWORD_RESET_REQUESTED', 'Password Reset Requested'
    PASSWORD_RESET_COMPLETED = 'PASSWORD_RESET_COMPLETED', 'Password Reset Completed'
    ACCOUNT_LOCKED = 'ACCOUNT_LOCKED', 'Account Locked'
    ACCOUNT_UNLOCKED = 'ACCOUNT_UNLOCKED', 'Account Unlocked'
    USER_CREATED = 'USER_CREATED', 'User Created'
    USER_UPDATED = 'USER_UPDATED', 'User Profile Updated'
    USER_DEACTIVATED = 'USER_DEACTIVATED', 'User Deactivated'
    USER_REACTIVATED = 'USER_REACTIVATED', 'User Reactivated'
    ROLE_CHANGED = 'ROLE_CHANGED', 'User Role Changed'
    PERMISSION_GRANTED = 'PERMISSION_GRANTED', 'Permission Granted'
    PERMISSION_REVOKED = 'PERMISSION_REVOKED', 'Permission Revoked'
    SENSITIVE_DATA_ACCESSED = 'SENSITIVE_DATA_ACCESSED', 'Sensitive Data Accessed'
    ADMIN_ACTION = 'ADMIN_ACTION', 'Administrative Action Performed'
    API_ACCESS_DENIED = 'API_ACCESS_DENIED', 'API Access Denied (401/403)'
    WEBHOOK_SECURITY_FAILURE = 'WEBHOOK_SECURITY_FAILURE', 'Webhook Signature/Security Failure'
    INTEGRATION_SECURITY_FAILURE = 'INTEGRATION_SECURITY_FAILURE', 'Integration Security Failure'
    SUSPICIOUS_ACTIVITY = 'SUSPICIOUS_ACTIVITY', 'Suspicious Activity Detected'
    SECURITY_POLICY_VIOLATION = 'SECURITY_POLICY_VIOLATION', 'Security Policy Violation'


class SecurityAuditEvent(models.Model):
    """
    Immutable, tamper-evident security audit log record with SHA-256 hash chaining.
    """
    event_type = models.CharField(max_length=50, choices=SecurityAuditEventType.choices, db_index=True)
    severity = models.CharField(max_length=20, choices=SecurityAuditEventSeverity.choices, default=SecurityAuditEventSeverity.INFO, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_actions_performed'
    )
    actor_role = models.CharField(max_length=50, blank=True)

    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='security_events_targeted'
    )
    target_model = models.CharField(max_length=100, blank=True)
    target_object_id = models.CharField(max_length=255, blank=True)

    action = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    request_id = models.CharField(max_length=255, blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    endpoint = models.CharField(max_length=500, blank=True)
    http_method = models.CharField(max_length=10, blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    previous_hash = models.CharField(max_length=64, blank=True)
    event_hash = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Security Audit Event'
        verbose_name_plural = 'Security Audit Events'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at', 'event_type']),
            models.Index(fields=['actor', 'created_at']),
            models.Index(fields=['target_user', 'created_at']),
            models.Index(fields=['severity', 'created_at']),
        ]

    def __str__(self):
        actor_str = self.actor.email if self.actor else "System/Anonymous"
        return f"Audit #{self.id} [{self.severity}] {self.event_type} by {actor_str} at {self.created_at}"


class SecurityIncidentStatus(models.TextChoices):
    OPEN = 'OPEN', 'Open'
    INVESTIGATING = 'INVESTIGATING', 'Under Investigation'
    CONTAINED = 'CONTAINED', 'Contained'
    RESOLVED = 'RESOLVED', 'Resolved'
    DISMISSED = 'DISMISSED', 'Dismissed / False Positive'


class SecurityIncidentType(models.TextChoices):
    BRUTE_FORCE = 'BRUTE_FORCE', 'Brute Force Attack'
    ACCOUNT_COMPROMISE = 'ACCOUNT_COMPROMISE', 'Account Compromise Suspected'
    PRIVILEGE_ESCALATION = 'PRIVILEGE_ESCALATION', 'Privilege Escalation Attempt'
    SUSPICIOUS_API_ACCESS = 'SUSPICIOUS_API_ACCESS', 'Suspicious API Access'
    SUSPICIOUS_LOGIN = 'SUSPICIOUS_LOGIN', 'Suspicious Login Activity'
    WEBHOOK_ATTACK = 'WEBHOOK_ATTACK', 'Webhook Tampering / Signature Failure'
    INTEGRATION_SECURITY_FAILURE = 'INTEGRATION_SECURITY_FAILURE', 'Integration Authentication Failure'
    UNAUTHORIZED_DATA_ACCESS = 'UNAUTHORIZED_DATA_ACCESS', 'Unauthorized Data Access Attempt'
    POLICY_VIOLATION = 'POLICY_VIOLATION', 'Security Policy Violation'
    AUDIT_INTEGRITY_FAILURE = 'AUDIT_INTEGRITY_FAILURE', 'Audit Chain Hash Integrity Violation'


class SecurityIncident(models.Model):
    """
    Security incident record tracking security threats, investigations, and resolution actions.
    """
    incident_type = models.CharField(max_length=50, choices=SecurityIncidentType.choices, db_index=True)
    severity = models.CharField(max_length=20, choices=SecurityAuditEventSeverity.choices, default=SecurityAuditEventSeverity.MEDIUM, db_index=True)
    status = models.CharField(max_length=20, choices=SecurityIncidentStatus.choices, default=SecurityIncidentStatus.OPEN, db_index=True)

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    detected_at = models.DateTimeField(auto_now_add=True, db_index=True)
    detected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='detected_incidents'
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_incidents'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_notes = models.TextField(blank=True)

    correlation_id = models.CharField(max_length=255, blank=True, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Security Incident'
        verbose_name_plural = 'Security Incidents'
        ordering = ['-detected_at']

    def __str__(self):
        return f"Incident #{self.id} [{self.severity}] {self.title} -> {self.status}"


class SecurityPolicy(models.Model):
    """
    Configurable deterministic security policy threshold and governance rule.
    """
    name = models.CharField(max_length=255, unique=True)
    policy_type = models.CharField(max_length=100, db_index=True)
    enabled = models.BooleanField(default=True, db_index=True)

    threshold = models.PositiveIntegerField(default=5)
    window_seconds = models.PositiveIntegerField(default=600)
    severity = models.CharField(max_length=20, choices=SecurityAuditEventSeverity.choices, default=SecurityAuditEventSeverity.HIGH)

    description = models.TextField(blank=True)
    configuration = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_security_policies'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_security_policies'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Security Policy'
        verbose_name_plural = 'Security Policies'
        ordering = ['name']

    def __str__(self):
        return f"Security Policy '{self.name}' ({self.policy_type}) - Enabled: {self.enabled}"






