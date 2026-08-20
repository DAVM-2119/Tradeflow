import uuid
from django.db import models
from django.conf import settings
from apps.accounts.models import ShipperProfile, TransporterProfile, DriverProfile


class VehicleType(models.TextChoices):
    FLATBED = 'FLATBED', 'Flatbed Trailer'
    TANKER = 'TANKER', 'Fuel/Liquid Tanker'
    REFRIGERATED = 'REFRIGERATED', 'Refrigerated Truck'
    CONTAINER_CARRIER = 'CONTAINER_CARRIER', 'Container Carrier'
    BOX_TRUCK = 'BOX_TRUCK', 'Box Cargo Truck'
    OTHER = 'OTHER', 'Other Cargo Vehicle'


class FuelType(models.TextChoices):
    DIESEL = 'DIESEL', 'Diesel'
    PETROL = 'PETROL', 'Petrol'
    ELECTRIC = 'ELECTRIC', 'Electric'
    HYBRID = 'HYBRID', 'Hybrid'


class Vehicle(models.Model):
    """
    Fleet vehicle owned and managed by a Transporter.
    """
    transporter = models.ForeignKey(
        TransporterProfile,
        on_delete=models.CASCADE,
        related_name='vehicles'
    )
    plate_number = models.CharField(max_length=50, unique=True, db_index=True)
    vehicle_type = models.CharField(
        max_length=30,
        choices=VehicleType.choices,
        default=VehicleType.FLATBED,
        db_index=True
    )
    capacity_tonnes = models.DecimalField(max_digits=8, decimal_places=2)
    fuel_type = models.CharField(
        max_length=20,
        choices=FuelType.choices,
        default=FuelType.DIESEL
    )
    insurance_policy_number = models.CharField(max_length=100)
    insurance_expiration = models.DateField(null=True, blank=True)
    roadworthiness_certificate = models.CharField(max_length=100)
    roadworthiness_expiration = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Fleet Vehicle'
        verbose_name_plural = 'Fleet Vehicles'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['transporter', 'is_active']),
            models.Index(fields=['vehicle_type', 'capacity_tonnes']),
        ]

    def __str__(self):
        return f"{self.plate_number} ({self.get_vehicle_type_display()} - {self.capacity_tonnes}t)"


class LoadStatus(models.TextChoices):
    DRAFT = 'DRAFT', 'Draft'
    POSTED = 'POSTED', 'Posted on Spot Market'
    ASSIGNED = 'ASSIGNED', 'Assigned to Transporter'
    CANCELLED = 'CANCELLED', 'Cancelled'
    EXPIRED = 'EXPIRED', 'Expired'


class CargoLoad(models.Model):
    """
    Spot market cargo load posted by a Shipper.
    """
    shipper = models.ForeignKey(
        ShipperProfile,
        on_delete=models.CASCADE,
        related_name='posted_loads'
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
        default=VehicleType.FLATBED,
        db_index=True
    )
    pickup_date = models.DateField(db_index=True)
    delivery_date = models.DateField()
    target_price = models.DecimalField(max_digits=12, decimal_places=2)  # ETB
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
        indexes = [
            models.Index(fields=['origin', 'destination']),
            models.Index(fields=['status', 'required_vehicle_type']),
            models.Index(fields=['pickup_date', 'status']),
        ]

    def __str__(self):
        return f"Load #{self.id}: {self.title} ({self.origin} -> {self.destination}) [{self.status}]"


class BidStatus(models.TextChoices):
    SUBMITTED = 'SUBMITTED', 'Submitted'
    ACCEPTED = 'ACCEPTED', 'Accepted'
    REJECTED = 'REJECTED', 'Rejected'
    WITHDRAWN = 'WITHDRAWN', 'Withdrawn'


class Bid(models.Model):
    """
    Spot market bid submitted by a Transporter on a posted CargoLoad.
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
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # ETB
    estimated_pickup = models.DateTimeField(null=True, blank=True)
    estimated_delivery = models.DateTimeField(null=True, blank=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=['load', 'transporter'],
                name='unique_bid_per_transporter_per_load'
            )
        ]

    def __str__(self):
        return f"Bid #{self.id}: {self.amount} ETB on Load #{self.load.id} by {self.transporter.company_name} [{self.status}]"


# ============================================================================
# PHASE 6: SHIPMENT EXECUTION & REAL-TIME TRACKING MODELS
# ============================================================================

class ShipmentStatus(models.TextChoices):
    CREATED = 'CREATED', 'Shipment Created'
    DRIVER_ASSIGNED = 'DRIVER_ASSIGNED', 'Driver Assigned'
    AT_PICKUP = 'AT_PICKUP', 'Arrived at Pickup'
    IN_TRANSIT = 'IN_TRANSIT', 'In Transit'
    AT_DESTINATION = 'AT_DESTINATION', 'Arrived at Destination'
    DELIVERED = 'DELIVERED', 'Delivered'
    CANCELLED = 'CANCELLED', 'Cancelled'


class Shipment(models.Model):
    """
    Active corridor shipment execution record linked to an assigned load.
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
        return f"Shipment {self.tracking_number} ({self.origin} -> {self.destination}) [{self.status}]"


class LocationUpdate(models.Model):
    """
    Real-time GPS telemetry ping recorded along trade corridor.
    """
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.CASCADE,
        related_name='location_updates'
    )
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    speed_kmh = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    heading_degrees = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    location_name = models.CharField(max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'GPS Location Update'
        verbose_name_plural = 'GPS Location Updates'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['shipment', '-timestamp']),
        ]

    def __str__(self):
        return f"GPS Ping for {self.shipment.tracking_number}: ({self.latitude}, {self.longitude}) at {self.timestamp}"


class ShipmentMilestone(models.Model):
    """
    Immutable audit log tracking shipment status transition milestones.
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
        blank=True
    )
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'Shipment Milestone'
        verbose_name_plural = 'Shipment Milestones'
        ordering = ['-timestamp']

    def __str__(self):
        return f"Milestone for {self.shipment.tracking_number}: {self.status} at {self.timestamp}"


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
