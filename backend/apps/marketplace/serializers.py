from rest_framework import serializers
from apps.accounts.models import TransporterProfile, TransporterVerificationAudit, VerificationStatus, DriverProfile
from apps.marketplace.models import (
    Vehicle,
    VehicleType,
    FuelType,
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
    Rating,
    Route,
    RouteWaypoint,
    RouteRecalculation,
)


class VehicleSerializer(serializers.ModelSerializer):
    transporter_company = serializers.CharField(source='transporter.company_name', read_only=True)

    class Meta:
        model = Vehicle
        fields = (
            'id',
            'transporter',
            'transporter_company',
            'plate_number',
            'vehicle_type',
            'capacity_tonnes',
            'fuel_type',
            'insurance_policy_number',
            'insurance_expiration',
            'roadworthiness_certificate',
            'roadworthiness_expiration',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'transporter', 'created_at', 'updated_at')

    def validate_capacity_tonnes(self, value):
        if value <= 0:
            raise serializers.ValidationError("Vehicle capacity must be greater than 0 tonnes.")
        return value

    def validate_plate_number(self, value):
        instance = getattr(self, 'instance', None)
        normalized = value.strip().upper()
        qs = Vehicle.objects.filter(plate_number__iexact=normalized)
        if instance:
            qs = qs.exclude(pk=instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A vehicle with this plate number already exists.")
        return normalized


class TransporterVerificationActionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=[VerificationStatus.VERIFIED, VerificationStatus.SUSPENDED])
    reason = serializers.CharField(required=False, allow_blank=True)


class TransporterVerificationAuditSerializer(serializers.ModelSerializer):
    performed_by_email = serializers.EmailField(source='performed_by.email', read_only=True)

    class Meta:
        model = TransporterVerificationAudit
        fields = (
            'id',
            'transporter',
            'performed_by',
            'performed_by_email',
            'previous_status',
            'new_status',
            'reason',
            'created_at',
        )
        read_only_fields = fields


class TransporterDetailSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_full_name = serializers.CharField(source='user.get_full_name', read_only=True)
    vehicles = VehicleSerializer(many=True, read_only=True)

    class Meta:
        model = TransporterProfile
        fields = (
            'id',
            'user',
            'user_email',
            'user_full_name',
            'company_name',
            'trade_license_number',
            'tax_id',
            'verification_status',
            'vehicles',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'user', 'verification_status', 'created_at', 'updated_at')


class BidSerializer(serializers.ModelSerializer):
    transporter_company = serializers.CharField(source='transporter.company_name', read_only=True)
    transporter_verification_status = serializers.CharField(source='transporter.verification_status', read_only=True)
    proposed_vehicle_details = VehicleSerializer(source='proposed_vehicle', read_only=True)

    class Meta:
        model = Bid
        fields = (
            'id',
            'load',
            'transporter',
            'transporter_company',
            'transporter_verification_status',
            'proposed_vehicle',
            'proposed_vehicle_details',
            'amount',
            'estimated_pickup',
            'estimated_delivery',
            'notes',
            'status',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'load', 'transporter', 'status', 'created_at', 'updated_at')


class BidCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bid
        fields = (
            'proposed_vehicle',
            'amount',
            'estimated_pickup',
            'estimated_delivery',
            'notes',
        )

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError("Bid amount must be greater than 0 ETB.")
        return value


class CargoLoadSerializer(serializers.ModelSerializer):
    shipper_company = serializers.CharField(source='shipper.company_name', read_only=True)
    assigned_transporter_company = serializers.CharField(source='assigned_transporter.company_name', read_only=True)
    assigned_vehicle_plate = serializers.CharField(source='assigned_vehicle.plate_number', read_only=True)
    bids_count = serializers.IntegerField(source='bids.count', read_only=True)

    class Meta:
        model = CargoLoad
        fields = (
            'id',
            'shipper',
            'shipper_company',
            'title',
            'origin',
            'destination',
            'cargo_type',
            'weight_tonnes',
            'volume_cubic_meters',
            'required_vehicle_type',
            'pickup_date',
            'delivery_date',
            'target_price',
            'special_instructions',
            'status',
            'assigned_transporter',
            'assigned_transporter_company',
            'assigned_vehicle',
            'assigned_vehicle_plate',
            'bids_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'shipper', 'status', 'assigned_transporter', 'assigned_vehicle', 'created_at', 'updated_at')

    def validate_weight_tonnes(self, value):
        if value <= 0:
            raise serializers.ValidationError("Weight must be greater than 0 tonnes.")
        return value

    def validate_target_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Target price must be greater than 0 ETB.")
        return value

    def validate(self, attrs):
        pickup = attrs.get('pickup_date')
        delivery = attrs.get('delivery_date')
        if pickup and delivery and delivery < pickup:
            raise serializers.ValidationError({'delivery_date': 'Delivery date cannot be before pickup date.'})
        return attrs


class LocationUpdateSerializer(serializers.ModelSerializer):
    recorded_by_email = serializers.EmailField(source='recorded_by.email', read_only=True)

    class Meta:
        model = LocationUpdate
        fields = (
            'id',
            'shipment',
            'latitude',
            'longitude',
            'speed_kmh',
            'heading_degrees',
            'location_name',
            'recorded_by',
            'recorded_by_email',
            'timestamp',
        )
        read_only_fields = ('id', 'shipment', 'recorded_by', 'timestamp')


class ShipmentMilestoneSerializer(serializers.ModelSerializer):
    updated_by_email = serializers.EmailField(source='updated_by.email', read_only=True)

    class Meta:
        model = ShipmentMilestone
        fields = (
            'id',
            'shipment',
            'status',
            'location_name',
            'notes',
            'updated_by',
            'updated_by_email',
            'timestamp',
        )
        read_only_fields = fields


class ShipmentSerializer(serializers.ModelSerializer):
    load_title = serializers.CharField(source='load.title', read_only=True)
    shipper_company = serializers.CharField(source='load.shipper.company_name', read_only=True)
    transporter_company = serializers.CharField(source='transporter.company_name', read_only=True)
    vehicle_plate = serializers.CharField(source='vehicle.plate_number', read_only=True)
    driver_name = serializers.CharField(source='driver.user.get_full_name', read_only=True, default=None)
    latest_location = serializers.SerializerMethodField()
    milestones = ShipmentMilestoneSerializer(many=True, read_only=True)

    class Meta:
        model = Shipment
        fields = (
            'id',
            'tracking_number',
            'load',
            'load_title',
            'shipper_company',
            'transporter',
            'transporter_company',
            'vehicle',
            'vehicle_plate',
            'driver',
            'driver_name',
            'status',
            'estimated_arrival_at',
            'eta_updated_at',
            'eta_confidence',
            'eta_basis',
            'origin',
            'destination',
            'actual_pickup_time',
            'actual_delivery_time',
            'latest_location',
            'milestones',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields

    def get_latest_location(self, obj):
        latest = obj.location_updates.first()
        if latest:
            return LocationUpdateSerializer(latest).data
        return None


class AssignDriverSerializer(serializers.Serializer):
    driver_id = serializers.IntegerField()


class ShipmentStatusUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ShipmentStatus.choices)
    location_name = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class ShipmentDocumentSerializer(serializers.ModelSerializer):
    uploaded_by_email = serializers.EmailField(source='uploaded_by.email', read_only=True)

    class Meta:
        model = ShipmentDocument
        fields = (
            'id',
            'shipment',
            'document_type',
            'file_name',
            'file_size_bytes',
            'mime_type',
            'checksum_sha256',
            'uploaded_by',
            'uploaded_by_email',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'shipment', 'file_name', 'file_size_bytes', 'mime_type', 'checksum_sha256', 'uploaded_by', 'created_at', 'updated_at')


class ShipmentDocumentUploadSerializer(serializers.Serializer):
    document_type = serializers.ChoiceField(choices=DocumentType.choices, default=DocumentType.WAYBILL)
    file = serializers.FileField()
    notes = serializers.CharField(required=False, allow_blank=True)


class ProofOfDeliverySerializer(serializers.ModelSerializer):
    delivered_by_driver_name = serializers.CharField(source='delivered_by_driver.user.get_full_name', read_only=True, default=None)
    confirmed_by_shipper_email = serializers.EmailField(source='confirmed_by_shipper.email', read_only=True, default=None)

    class Meta:
        model = ProofOfDelivery
        fields = (
            'id',
            'shipment',
            'delivered_by_driver',
            'delivered_by_driver_name',
            'recipient_name',
            'recipient_phone',
            'delivery_location',
            'delivered_at',
            'signature_data',
            'cargo_condition',
            'received_weight_tonnes',
            'delivery_notes',
            'confirmation_status',
            'confirmed_by_shipper',
            'confirmed_by_shipper_email',
            'confirmed_at',
            'dispute_reason',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'shipment', 'delivered_by_driver', 'confirmation_status', 'confirmed_by_shipper', 'confirmed_at', 'created_at', 'updated_at')


class PODCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProofOfDelivery
        fields = (
            'recipient_name',
            'recipient_phone',
            'delivery_location',
            'delivered_at',
            'signature_data',
            'cargo_condition',
            'received_weight_tonnes',
            'delivery_notes',
        )


class PODDisputeSerializer(serializers.Serializer):
    dispute_reason = serializers.CharField(required=True)


class FreightInvoiceSerializer(serializers.ModelSerializer):
    issuer_email = serializers.EmailField(source='issuer.email', read_only=True, default=None)
    payer_email = serializers.EmailField(source='payer.email', read_only=True, default=None)

    class Meta:
        model = FreightInvoice
        fields = (
            'id',
            'invoice_number',
            'shipment',
            'issuer',
            'issuer_email',
            'payer',
            'payer_email',
            'subtotal_amount',
            'commission_amount',
            'total_amount',
            'currency',
            'status',
            'issue_date',
            'due_date',
            'paid_date',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class FreightSettlementSerializer(serializers.ModelSerializer):
    shipment_tracking_number = serializers.CharField(source='shipment.tracking_number', read_only=True)
    invoice_number = serializers.CharField(source='invoice.invoice_number', read_only=True, default=None)

    class Meta:
        model = FreightSettlement
        fields = (
            'id',
            'shipment',
            'shipment_tracking_number',
            'invoice',
            'invoice_number',
            'gross_freight_amount',
            'commission_rate',
            'platform_commission_amount',
            'transporter_net_payable',
            'status',
            'settled_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    payer_email = serializers.EmailField(source='payer.email', read_only=True, default=None)

    class Meta:
        model = Payment
        fields = (
            'id',
            'idempotency_key',
            'shipment',
            'settlement',
            'payer',
            'payer_email',
            'amount',
            'currency',
            'provider',
            'provider_transaction_id',
            'payment_method',
            'status',
            'initiated_at',
            'confirmed_at',
            'failed_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class PaymentInitiateSerializer(serializers.Serializer):
    settlement_id = serializers.IntegerField()
    idempotency_key = serializers.CharField(max_length=100)
    provider_name = serializers.CharField(max_length=50, default='MOCK', required=False)


class TransporterPayoutSerializer(serializers.ModelSerializer):
    transporter_company = serializers.CharField(source='transporter.company_name', read_only=True)

    class Meta:
        model = TransporterPayout
        fields = (
            'id',
            'settlement',
            'transporter',
            'transporter_company',
            'gross_amount',
            'commission_amount',
            'net_payout_amount',
            'status',
            'payout_reference',
            'scheduled_at',
            'processed_at',
            'failure_reason',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class PaymentDisputeSerializer(serializers.ModelSerializer):
    raised_by_email = serializers.EmailField(source='raised_by.email', read_only=True)
    resolved_by_email = serializers.EmailField(source='resolved_by.email', read_only=True, default=None)

    class Meta:
        model = PaymentDispute
        fields = (
            'id',
            'payment',
            'settlement',
            'raised_by',
            'raised_by_email',
            'reason',
            'status',
            'resolution_notes',
            'resolved_by',
            'resolved_by_email',
            'resolved_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class DisputeRaiseSerializer(serializers.Serializer):
    reason = serializers.CharField(required=True)


class DisputeResolveSerializer(serializers.Serializer):
    resolution_notes = serializers.CharField(required=True)
    status = serializers.ChoiceField(choices=[PaymentDisputeStatus.RESOLVED, PaymentDisputeStatus.REJECTED], default=PaymentDisputeStatus.RESOLVED)


# ============================================================================
# PHASE 9: OFFLINE-FIRST SYNCHRONIZATION SERIALIZERS (SRS 2.4, 4.1, 5.2)
# ============================================================================

class OfflineSyncEventInputSerializer(serializers.Serializer):
    client_event_id = serializers.CharField(max_length=100)
    event_type = serializers.ChoiceField(choices=OfflineSyncEventType.choices)
    shipment_id = serializers.IntegerField()
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    client_created_at = serializers.DateTimeField()
    payload = serializers.JSONField(default=dict)


class OfflineSyncBatchInputSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    events = OfflineSyncEventInputSerializer(many=True)


class OfflineSyncEventResultSerializer(serializers.Serializer):
    client_event_id = serializers.CharField()
    status = serializers.ChoiceField(choices=OfflineSyncStatus.choices)
    event_type = serializers.CharField()
    server_record_id = serializers.IntegerField(allow_null=True)
    server_timestamp = serializers.DateTimeField()
    message = serializers.CharField()


class OfflineSyncBatchResponseSerializer(serializers.Serializer):
    total_events = serializers.IntegerField()
    synced_count = serializers.IntegerField()
    duplicate_count = serializers.IntegerField()
    failed_count = serializers.IntegerField()
    results = OfflineSyncEventResultSerializer(many=True)


class DriverIncidentReportSerializer(serializers.ModelSerializer):
    shipment_tracking_number = serializers.CharField(source='shipment.tracking_number', read_only=True)
    driver_name = serializers.CharField(source='driver.user.get_full_name', read_only=True)
    reported_by_email = serializers.EmailField(source='reported_by.email', read_only=True)

    class Meta:
        model = DriverIncidentReport
        fields = (
            'id',
            'shipment',
            'shipment_tracking_number',
            'driver',
            'driver_name',
            'reported_by',
            'reported_by_email',
            'incident_type',
            'latitude',
            'longitude',
            'location_name',
            'description',
            'reported_at',
            'offline_event',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'driver', 'reported_by', 'offline_event', 'created_at', 'updated_at')


class RatingSerializer(serializers.ModelSerializer):
    rater_email = serializers.EmailField(source='rater.email', read_only=True)
    ratee_email = serializers.EmailField(source='ratee.email', read_only=True)

    class Meta:
        model = Rating
        fields = (
            'id',
            'rater',
            'rater_email',
            'ratee',
            'ratee_email',
            'stars',
            'comment',
            'shipment',
            'created_at',
        )
        read_only_fields = ('id', 'rater', 'created_at')

    def validate_stars(self, value):
        if value < 1 or value > 5:
            raise serializers.ValidationError("Rating must be between 1 and 5 stars.")
        return value


# ============================================================================
# PHASE 10: ROUTE OPTIMIZATION, ETA & FUEL ANALYTICS SERIALIZERS
# ============================================================================

class RouteWaypointSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteWaypoint
        fields = (
            'id',
            'sequence',
            'location_name',
            'latitude',
            'longitude',
            'expected_arrival_time',
            'expected_departure_time',
            'distance_from_previous_km',
            'travel_time_from_previous_hours',
        )


class RouteSerializer(serializers.ModelSerializer):
    waypoints = RouteWaypointSerializer(many=True, read_only=True)

    class Meta:
        model = Route
        fields = (
            'id',
            'shipment',
            'is_active',
            'origin',
            'origin_latitude',
            'origin_longitude',
            'destination',
            'destination_latitude',
            'destination_longitude',
            'total_distance_km',
            'estimated_duration_hours',
            'estimated_arrival_time',
            'status',
            'average_speed_kmh',
            'waypoints',
            'created_at',
            'updated_at',
        )


class RouteWaypointInputSerializer(serializers.Serializer):
    sequence = serializers.IntegerField(min_value=1)
    location_name = serializers.CharField(max_length=255)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    expected_arrival_time = serializers.DateTimeField(required=False, allow_null=True)
    expected_departure_time = serializers.DateTimeField(required=False, allow_null=True)

    def validate_latitude(self, value):
        if value < -90 or value > 90:
            raise serializers.ValidationError("Latitude must be between -90.0 and 90.0 degrees.")
        return value

    def validate_longitude(self, value):
        if value < -180 or value > 180:
            raise serializers.ValidationError("Longitude must be between -180.0 and 180.0 degrees.")
        return value


class RouteCreateInputSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=255, required=False, allow_blank=True)
    destination = serializers.CharField(max_length=255, required=False, allow_blank=True)
    average_speed_kmh = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, default=50.00)
    waypoints = RouteWaypointInputSerializer(many=True)

    def validate_waypoints(self, value):
        if len(value) < 2:
            raise serializers.ValidationError("A route must contain at least 2 waypoints (origin and destination).")
        return value


class RouteRecalculateInputSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, default="Route recalculation requested")
    incident_id = serializers.IntegerField(required=False, allow_null=True)
    waypoints = RouteWaypointInputSerializer(many=True, required=False)


class RouteRecalculationSerializer(serializers.ModelSerializer):
    previous_route_id = serializers.IntegerField(source='previous_route.id', read_only=True, allow_null=True)
    new_route_id = serializers.IntegerField(source='new_route.id', read_only=True)
    triggered_by_email = serializers.EmailField(source='triggered_by.email', read_only=True, allow_null=True)

    class Meta:
        model = RouteRecalculation
        fields = (
            'id',
            'shipment',
            'previous_route_id',
            'new_route_id',
            'triggered_by_email',
            'incident',
            'reason',
            'previous_distance_km',
            'new_distance_km',
            'previous_eta',
            'new_eta',
            'recalculated_at',
        )


class LiveETAResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    has_active_route = serializers.BooleanField()
    total_route_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    traveled_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    remaining_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    average_speed_kmh = serializers.DecimalField(max_digits=5, decimal_places=2)
    remaining_duration_hours = serializers.DecimalField(max_digits=6, decimal_places=2)
    estimated_arrival_time = serializers.DateTimeField(allow_null=True)
    message = serializers.CharField()


class FuelAnalyticsResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    fuel_efficiency_km_per_liter = serializers.DecimalField(max_digits=5, decimal_places=2)
    fuel_price_per_liter_etb = serializers.DecimalField(max_digits=8, decimal_places=2)
    planned_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    planned_fuel_used_liters = serializers.DecimalField(max_digits=10, decimal_places=2)
    planned_fuel_cost_etb = serializers.DecimalField(max_digits=12, decimal_places=2)
    actual_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    actual_fuel_used_liters = serializers.DecimalField(max_digits=10, decimal_places=2)
    actual_fuel_cost_etb = serializers.DecimalField(max_digits=12, decimal_places=2)
    message = serializers.CharField()


class RouteDeviationResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    status = serializers.CharField()
    min_distance_to_route_km = serializers.DecimalField(max_digits=8, decimal_places=2, allow_null=True)
    threshold_km = serializers.DecimalField(max_digits=8, decimal_places=2)
    latest_gps_location = serializers.DictField(required=False, allow_null=True)
    message = serializers.CharField()


class RouteAnalyticsResponseSerializer(serializers.Serializer):
    shipment_id = serializers.IntegerField()
    tracking_number = serializers.CharField()
    has_active_route = serializers.BooleanField()
    planned_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    actual_distance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    distance_variance_km = serializers.DecimalField(max_digits=10, decimal_places=2)
    planned_duration_hours = serializers.DecimalField(max_digits=6, decimal_places=2)
    actual_duration_hours = serializers.DecimalField(max_digits=6, decimal_places=2)
    duration_variance_hours = serializers.DecimalField(max_digits=6, decimal_places=2)
    route_efficiency_percentage = serializers.DecimalField(max_digits=6, decimal_places=2)
    deviation_status = serializers.CharField()
    fuel_analytics = FuelAnalyticsResponseSerializer()
    recalculation_count = serializers.IntegerField()
    incident_count = serializers.IntegerField()


