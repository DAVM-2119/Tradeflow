from django.db import models
from django.conf import settings
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
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

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
    timestamp = models.DateTimeField(auto_now_add=True)

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
