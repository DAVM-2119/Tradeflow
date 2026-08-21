import pytest
from django.db import IntegrityError
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


@pytest.mark.django_db
def test_create_user_success():
    """Verify custom User creation with email and password hashing."""
    user = User.objects.create_user(
        email='shipper@tradeflow.et',
        password='SecurePassword123!',
        first_name='Abebe',
        last_name='Bikila',
        role=Role.SHIPPER
    )
    assert user.pk is not None
    assert user.email == 'shipper@tradeflow.et'
    assert user.role == Role.SHIPPER
    assert user.check_password('SecurePassword123!') is True
    assert user.is_active is True
    assert user.is_staff is False


@pytest.mark.django_db
def test_create_superuser_success():
    """Verify superuser creation with email and ADMIN role."""
    admin = User.objects.create_superuser(
        email='admin@tradeflow.et',
        password='AdminPassword123!',
        first_name='Admin',
        last_name='System'
    )
    assert admin.pk is not None
    assert admin.role == Role.ADMIN
    assert admin.is_staff is True
    assert admin.is_superuser is True


@pytest.mark.django_db
def test_user_email_unique_constraint():
    """Verify duplicate email throws IntegrityError."""
    User.objects.create_user(email='duplicate@tradeflow.et', password='Password123!')
    with pytest.raises(IntegrityError):
        User.objects.create_user(email='duplicate@tradeflow.et', password='Password123!')


@pytest.mark.django_db
def test_shipper_profile_creation():
    """Verify ShipperProfile linked to User entity."""
    user = User.objects.create_user(
        email='shipper_company@tradeflow.et',
        password='Password123!',
        role=Role.SHIPPER
    )
    shipper = ShipperProfile.objects.create(
        user=user,
        company_name='Ethiopian Import Export Trading PLC',
        trade_license_number='TL-998877',
        tax_id='TIN-11223344',
        address='Addis Ababa, Kirkos Subcity'
    )
    assert shipper.pk is not None
    assert user.shipper_profile == shipper
    assert str(shipper).startswith('Shipper: Ethiopian Import Export Trading PLC')


@pytest.mark.django_db
def test_transporter_profile_and_verification_status():
    """Verify TransporterProfile creation with default PENDING verification status."""
    user = User.objects.create_user(
        email='transporter@tradeflow.et',
        password='Password123!',
        role=Role.TRANSPORTER
    )
    transporter = TransporterProfile.objects.create(
        user=user,
        company_name='Abyssinia Logistics Transporter PLC',
        trade_license_number='TL-554433',
        tax_id='TIN-99887766'
    )
    assert transporter.verification_status == VerificationStatus.PENDING
    assert str(transporter).startswith('Transporter: Abyssinia Logistics Transporter PLC')


@pytest.mark.django_db
def test_driver_profile_relationship():
    """Verify DriverProfile FK relationship to TransporterProfile."""
    trans_user = User.objects.create_user(email='fleet_owner@tradeflow.et', password='Password123!', role=Role.TRANSPORTER)
    transporter = TransporterProfile.objects.create(
        user=trans_user,
        company_name='Horn Freight Lines',
        trade_license_number='TL-771122',
        tax_id='TIN-33221144'
    )
    driver_user = User.objects.create_user(email='driver1@tradeflow.et', password='Password123!', role=Role.DRIVER)
    driver = DriverProfile.objects.create(
        user=driver_user,
        transporter=transporter,
        license_number='DL-ETH-88221'
    )
    assert driver.transporter == transporter
    assert transporter.drivers.count() == 1


@pytest.mark.django_db
def test_customs_staff_profile():
    """Verify CustomsStaffProfile creation."""
    user = User.objects.create_user(email='customs_officer@tradeflow.et', password='Password123!', role=Role.CUSTOMS_STAFF)
    customs = CustomsStaffProfile.objects.create(
        user=user,
        badge_number='ECC-BADGE-4402',
        station_location='Modjo Dry Port'
    )
    assert customs.station_location == 'Modjo Dry Port'
    assert user.customs_profile == customs
