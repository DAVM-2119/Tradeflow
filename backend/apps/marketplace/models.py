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

