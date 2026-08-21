from django.db import transaction
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from apps.accounts.models import (
    User,
    Role,
    VerificationStatus,
    ShipperProfile,
    TransporterProfile,
    DriverProfile,
    FreightForwarderProfile,
    CustomsStaffProfile,
)


class ShipperProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShipperProfile
        fields = ('company_name', 'trade_license_number', 'tax_id', 'address', 'created_at')


class TransporterProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = TransporterProfile
        fields = ('company_name', 'trade_license_number', 'tax_id', 'verification_status', 'created_at')


class DriverProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverProfile
        fields = ('license_number', 'license_expiration', 'transporter', 'created_at')


class FreightForwarderProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = FreightForwarderProfile
        fields = ('company_name', 'license_number', 'created_at')


class CustomsStaffProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomsStaffProfile
        fields = ('badge_number', 'station_location', 'created_at')


class UserSerializer(serializers.ModelSerializer):
    profile = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id',
            'email',
            'first_name',
            'last_name',
            'phone_number',
            'role',
            'is_active',
            'is_staff',
            'profile',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'is_active', 'is_staff', 'created_at', 'updated_at')

    def get_profile(self, obj):
        if hasattr(obj, 'shipper_profile'):
            return ShipperProfileSerializer(obj.shipper_profile).data
        elif hasattr(obj, 'transporter_profile'):
            return TransporterProfileSerializer(obj.transporter_profile).data
        elif hasattr(obj, 'driver_profile'):
            return DriverProfileSerializer(obj.driver_profile).data
        elif hasattr(obj, 'forwarder_profile'):
            return FreightForwarderProfileSerializer(obj.forwarder_profile).data
        elif hasattr(obj, 'customs_profile'):
            return CustomsStaffProfileSerializer(obj.customs_profile).data
        return None


class UserRegisterSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(required=True)
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    first_name = serializers.CharField(required=True, max_length=150)
    last_name = serializers.CharField(required=True, max_length=150)
    phone_number = serializers.CharField(required=False, allow_blank=True, max_length=30)
    role = serializers.ChoiceField(choices=Role.choices, default=Role.SHIPPER)

    # Optional nested profile fields for onboarding
    company_name = serializers.CharField(required=False, write_only=True, max_length=255)
    trade_license_number = serializers.CharField(required=False, write_only=True, max_length=100)
    tax_id = serializers.CharField(required=False, write_only=True, max_length=100)
    address = serializers.CharField(required=False, write_only=True, allow_blank=True)
    license_number = serializers.CharField(required=False, write_only=True, max_length=100)
    license_expiration = serializers.DateField(required=False, write_only=True, allow_null=True)
    badge_number = serializers.CharField(required=False, write_only=True, max_length=100)
    station_location = serializers.CharField(required=False, write_only=True, max_length=255)

    class Meta:
        model = User
        fields = (
            'email',
            'password',
            'first_name',
            'last_name',
            'phone_number',
            'role',
            'company_name',
            'trade_license_number',
            'tax_id',
            'address',
            'license_number',
            'license_expiration',
            'badge_number',
            'station_location',
        )

    def validate_email(self, value):
        normalized_email = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=normalized_email).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized_email

    def validate_role(self, value):
        if value == Role.ADMIN:
            raise serializers.ValidationError("Users cannot self-register as ADMIN.")
        if value not in Role.values:
            raise serializers.ValidationError("Invalid user role specified.")
        return value

    def create(self, validated_data):
        # Extract profile fields
        company_name = validated_data.pop('company_name', '')
        trade_license_number = validated_data.pop('trade_license_number', '')
        tax_id = validated_data.pop('tax_id', '')
        address = validated_data.pop('address', '')
        license_number = validated_data.pop('license_number', '')
        license_expiration = validated_data.pop('license_expiration', None)
        badge_number = validated_data.pop('badge_number', '')
        station_location = validated_data.pop('station_location', 'Modjo Dry Port')

        password = validated_data.pop('password')
        role = validated_data.get('role', Role.SHIPPER)

        with transaction.atomic():
            user = User.objects.create_user(
                password=password,
                **validated_data
            )

            # Initialize domain profile based on role if fields are provided or defaults
            if role == Role.SHIPPER and (company_name or trade_license_number or tax_id):
                ShipperProfile.objects.create(
                    user=user,
                    company_name=company_name or f"{user.get_full_name()} Company",
                    trade_license_number=trade_license_number or f"TL-REG-{user.id}",
                    tax_id=tax_id or f"TIN-REG-{user.id}",
                    address=address
                )
            elif role == Role.TRANSPORTER and (company_name or trade_license_number or tax_id):
                TransporterProfile.objects.create(
                    user=user,
                    company_name=company_name or f"{user.get_full_name()} Transport",
                    trade_license_number=trade_license_number or f"TL-TRANS-{user.id}",
                    tax_id=tax_id or f"TIN-TRANS-{user.id}",
                    verification_status=VerificationStatus.PENDING
                )
            elif role == Role.DRIVER and license_number:
                DriverProfile.objects.create(
                    user=user,
                    license_number=license_number,
                    license_expiration=license_expiration
                )
            elif role == Role.FREIGHT_FORWARDER and (company_name or license_number):
                FreightForwarderProfile.objects.create(
                    user=user,
                    company_name=company_name or f"{user.get_full_name()} Forwarder",
                    license_number=license_number or f"LIC-FF-{user.id}"
                )
            elif role == Role.CUSTOMS_STAFF and badge_number:
                CustomsStaffProfile.objects.create(
                    user=user,
                    badge_number=badge_number,
                    station_location=station_location
                )

        return user


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom JWT token obtain serializer verifying active user state and
    including user info in response.
    """
    username_field = User.USERNAME_FIELD

    def validate(self, attrs):
        data = super().validate(attrs)
        if not self.user.is_active:
            raise serializers.ValidationError({"detail": "Inactive user account cannot authenticate."})
        
        data['user'] = {
            'id': self.user.id,
            'email': self.user.email,
            'first_name': self.user.first_name,
            'last_name': self.user.last_name,
            'role': self.user.role,
        }
        return data
