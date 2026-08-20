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
    Rating,
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


# ============================================================================
# PHASE 7: DOCUMENT MANAGEMENT & DIGITAL PROOF OF DELIVERY (e-POD) SERIALIZERS
# ============================================================================

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
