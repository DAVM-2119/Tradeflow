import pytest
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.accounts.models import Role, VerificationStatus, ShipperProfile, TransporterProfile, TransporterVerificationAudit
from apps.marketplace.models import Vehicle, VehicleType, FuelType, Rating
from apps.marketplace.services import VerificationService, FleetService
from apps.marketplace.permissions import IsTransporterVerified

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(email="admin_market@tradeflow.et", password="AdminPassword123!")


@pytest.fixture
def transporter_user():
    user = User.objects.create_user(email="transporter_owner@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    transporter = TransporterProfile.objects.create(
        user=user,
        company_name="Ethio Cargo Express PLC",
        trade_license_number="TL-ETHIO-1001",
        tax_id="TIN-ETHIO-1001",
        verification_status=VerificationStatus.PENDING
    )
    return user


@pytest.fixture
def shipper_user():
    user = User.objects.create_user(email="shipper_owner@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    shipper = ShipperProfile.objects.create(
        user=user,
        company_name="Red Sea Imports PLC",
        trade_license_number="TL-REDSEA-9001",
        tax_id="TIN-REDSEA-9001",
        address="Modjo Industrial Park"
    )
    return user


@pytest.mark.django_db
def test_shipper_onboarding_succeeds(api_client, shipper_user):
    """1. Shipper onboarding profile view and data integrity."""
    api_client.force_authenticate(user=shipper_user)
    res = api_client.get('/api/v1/auth/me/')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['profile']['company_name'] == "Red Sea Imports PLC"


@pytest.mark.django_db
def test_transporter_onboarding_starts_as_pending(api_client):
    """2 & 3. Transporter registration starts in PENDING status."""
    payload = {
        "email": "new_transporter@tradeflow.et",
        "password": "StrongPassword123!",
        "first_name": "Tewodros",
        "last_name": "Kassa",
        "role": "TRANSPORTER",
        "company_name": "Kassa Fleet",
        "trade_license_number": "TL-KASSA-55",
        "tax_id": "TIN-KASSA-55"
    }
    res = api_client.post('/api/v1/auth/register/', payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    assert res.json()['profile']['verification_status'] == "PENDING"


@pytest.mark.django_db
def test_transporter_cannot_self_verify(api_client, transporter_user):
    """4. Transporter cannot alter their own verification status via profile PATCH."""
    api_client.force_authenticate(user=transporter_user)
    res = api_client.patch('/api/v1/transporters/me/', {"verification_status": "VERIFIED"}, format='json')
    assert res.status_code == status.HTTP_200_OK
    # Verification status remains PENDING
    assert transporter_user.transporter_profile.verification_status == VerificationStatus.PENDING


@pytest.mark.django_db
def test_admin_can_verify_transporter(api_client, admin_user, transporter_user):
    """5. Admin can verify transporter via API and audit record is logged."""
    api_client.force_authenticate(user=admin_user)
    trans_id = transporter_user.transporter_profile.id
    payload = {
        "status": "VERIFIED",
        "reason": "Business license and roadworthiness documents verified by ECC."
    }
    res = api_client.post(f'/api/v1/transporters/{trans_id}/verification/', payload, format='json')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['verification_status'] == "VERIFIED"

    # Check audit record
    audit = TransporterVerificationAudit.objects.filter(transporter_id=trans_id).latest('created_at')
    assert audit.previous_status == VerificationStatus.PENDING
    assert audit.new_status == VerificationStatus.VERIFIED
    assert audit.performed_by == admin_user


@pytest.mark.django_db
def test_admin_can_suspend_transporter(api_client, admin_user, transporter_user):
    """6. Admin can suspend transporter via API."""
    api_client.force_authenticate(user=admin_user)
    trans_id = transporter_user.transporter_profile.id
    payload = {
        "status": "SUSPENDED",
        "reason": "Suspended due to safety compliance audit."
    }
    res = api_client.post(f'/api/v1/transporters/{trans_id}/verification/', payload, format='json')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['verification_status'] == "SUSPENDED"


@pytest.mark.django_db
def test_transporter_can_create_own_vehicle(api_client, transporter_user):
    """8. Transporter creates vehicle in their fleet."""
    api_client.force_authenticate(user=transporter_user)
    payload = {
        "plate_number": "ET-3-99881",
        "vehicle_type": "FLATBED",
        "capacity_tonnes": 40.50,
        "fuel_type": "DIESEL",
        "insurance_policy_number": "POL-992211",
        "roadworthiness_certificate": "ROAD-CERT-8877"
    }
    res = api_client.post('/api/v1/transporters/me/vehicles/', payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data['plate_number'] == "ET-3-99881"
    assert float(data['capacity_tonnes']) == 40.50


@pytest.mark.django_db
def test_transporter_cannot_modify_other_transporter_vehicle(api_client, transporter_user):
    """9. Transporter cannot update or delete another transporter's vehicle."""
    other_user = User.objects.create_user(email="other_trans@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    other_trans = TransporterProfile.objects.create(user=other_user, company_name="Other Fleet", trade_license_number="TL-OT-1", tax_id="TIN-OT-1")
    vehicle = Vehicle.objects.create(
        transporter=other_trans,
        plate_number="ET-3-11111",
        vehicle_type=VehicleType.TANKER,
        capacity_tonnes=30.00,
        insurance_policy_number="P1",
        roadworthiness_certificate="R1"
    )

    api_client.force_authenticate(user=transporter_user)
    patch_res = api_client.patch(f'/api/v1/transporters/me/vehicles/{vehicle.id}/', {"capacity_tonnes": 50.00}, format='json')
    assert patch_res.status_code in (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND)


@pytest.mark.django_db
def test_vehicle_plate_number_uniqueness(api_client, transporter_user):
    """10. Duplicate plate number registration fails validation."""
    api_client.force_authenticate(user=transporter_user)
    payload = {
        "plate_number": "ET-3-DUP",
        "vehicle_type": "FLATBED",
        "capacity_tonnes": 35.00,
        "insurance_policy_number": "P1",
        "roadworthiness_certificate": "R1"
    }
    api_client.post('/api/v1/transporters/me/vehicles/', payload, format='json')
    res = api_client.post('/api/v1/transporters/me/vehicles/', payload, format='json')
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "plate_number" in res.json()


@pytest.mark.django_db
def test_unauthenticated_users_rejected(api_client):
    """13. Unauthenticated requests to fleet endpoints get 401 Unauthorized."""
    res = api_client.get('/api/v1/transporters/me/vehicles/')
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_critical_acceptance_unverified_transporter_rejected(admin_user, transporter_user):
    """
    CRITICAL ACCEPTANCE TEST:
    Proves that an unverified (PENDING or SUSPENDED) transporter is rejected
    by VerificationService.can_accept_load() and IsTransporterVerified permission.
    """
    transporter = transporter_user.transporter_profile

    # PENDING state check
    assert transporter.verification_status == VerificationStatus.PENDING
    assert VerificationService.can_accept_load(transporter_user) is False
    assert VerificationService.can_accept_load(transporter) is False

    class MockRequest:
        def __init__(self, user):
            self.user = user

    pending_req = MockRequest(transporter_user)
    perm = IsTransporterVerified()
    assert perm.has_permission(pending_req, None) is False

    # VERIFIED state check
    VerificationService.verify_transporter(transporter, admin_user, reason="Verified for acceptance test.")
    transporter.refresh_from_db()
    assert transporter.verification_status == VerificationStatus.VERIFIED
    assert VerificationService.can_accept_load(transporter_user) is True
    assert perm.has_permission(pending_req, None) is True

    # SUSPENDED state check
    VerificationService.suspend_transporter(transporter, admin_user, reason="Suspended for acceptance test.")
    transporter.refresh_from_db()
    assert transporter.verification_status == VerificationStatus.SUSPENDED
    assert VerificationService.can_accept_load(transporter_user) is False
    assert perm.has_permission(pending_req, None) is False


@pytest.mark.django_db
def test_rating_creation_and_validation(api_client, shipper_user, transporter_user):
    """14. Post-trip rating submission and star rating range validation."""
    api_client.force_authenticate(user=shipper_user)
    payload = {
        "ratee": transporter_user.id,
        "stars": 5,
        "comment": "Outstanding corridor transport performance on Djibouti route!"
    }
    res = api_client.post('/api/v1/ratings/', payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    assert res.json()['stars'] == 5

    # Invalid star rating (6 stars)
    invalid_payload = {
        "ratee": transporter_user.id,
        "stars": 6
    }
    inv_res = api_client.post('/api/v1/ratings/', invalid_payload, format='json')
    assert inv_res.status_code == status.HTTP_400_BAD_REQUEST
