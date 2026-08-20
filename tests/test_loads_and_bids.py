import pytest
from datetime import date, timedelta
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.accounts.models import Role, VerificationStatus, ShipperProfile, TransporterProfile
from apps.marketplace.models import Vehicle, VehicleType, FuelType, CargoLoad, LoadStatus, Bid, BidStatus
from apps.marketplace.services import VerificationService

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(email="admin_phase5@tradeflow.et", password="AdminPassword123!")


@pytest.fixture
def shipper_user():
    user = User.objects.create_user(email="shipper_phase5@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    ShipperProfile.objects.create(
        user=user,
        company_name="Ethiopia Grain Trade Enterprise",
        trade_license_number="TL-GRAIN-01",
        tax_id="TIN-GRAIN-01"
    )
    return user


@pytest.fixture
def pending_transporter_user():
    user = User.objects.create_user(email="transporter_pending@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    TransporterProfile.objects.create(
        user=user,
        company_name="Pending Freight PLC",
        trade_license_number="TL-PEND-01",
        tax_id="TIN-PEND-01",
        verification_status=VerificationStatus.PENDING
    )
    return user


@pytest.fixture
def verified_transporter_user(admin_user):
    user = User.objects.create_user(email="transporter_verified@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    trans = TransporterProfile.objects.create(
        user=user,
        company_name="Verified Corridor Express PLC",
        trade_license_number="TL-VER-01",
        tax_id="TIN-VER-01",
        verification_status=VerificationStatus.PENDING
    )
    VerificationService.verify_transporter(trans, admin_user, reason="Verified for Phase 5 testing.")
    return user


@pytest.fixture
def verified_transporter_user2(admin_user):
    user = User.objects.create_user(email="transporter_verified2@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    trans = TransporterProfile.objects.create(
        user=user,
        company_name="Red Sea Transport PLC",
        trade_license_number="TL-VER-02",
        tax_id="TIN-VER-02",
        verification_status=VerificationStatus.PENDING
    )
    VerificationService.verify_transporter(trans, admin_user, reason="Verified for Phase 5 testing.")
    return user


@pytest.fixture
def transporter_vehicle(verified_transporter_user):
    return Vehicle.objects.create(
        transporter=verified_transporter_user.transporter_profile,
        plate_number="ET-3-10001",
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=40.00,
        insurance_policy_number="POL-101",
        roadworthiness_certificate="ROAD-101"
    )


@pytest.fixture
def transporter_vehicle2(verified_transporter_user2):
    return Vehicle.objects.create(
        transporter=verified_transporter_user2.transporter_profile,
        plate_number="ET-3-20002",
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=45.00,
        insurance_policy_number="POL-202",
        roadworthiness_certificate="ROAD-202"
    )


@pytest.mark.django_db
def test_shipper_can_post_cargo_load(api_client, shipper_user):
    """1. Shipper posts cargo load specifying corridor origin, destination, weight, and target price."""
    api_client.force_authenticate(user=shipper_user)
    payload = {
        "title": "40 Tonnes Bulk Wheat Import",
        "origin": "Djibouti Port",
        "destination": "Modjo Dry Port",
        "cargo_type": "Bulk Wheat",
        "weight_tonnes": 40.00,
        "volume_cubic_meters": 60.00,
        "required_vehicle_type": "FLATBED",
        "pickup_date": str(date.today() + timedelta(days=2)),
        "delivery_date": str(date.today() + timedelta(days=5)),
        "target_price": 120000.00,
        "special_instructions": "Handle with care. Tarpaulin cover required."
    }
    res = api_client.post('/api/v1/loads/', payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data['origin'] == "Djibouti Port"
    assert data['destination'] == "Modjo Dry Port"
    assert data['status'] == "POSTED"


@pytest.mark.django_db
def test_transporter_cannot_post_cargo_load(api_client, verified_transporter_user):
    """2. Transporter attempting to post a cargo load gets 403 Forbidden."""
    api_client.force_authenticate(user=verified_transporter_user)
    payload = {
        "title": "Unauthorized Load",
        "origin": "Addis Ababa",
        "destination": "Hawassa",
        "cargo_type": "General",
        "weight_tonnes": 10.00,
        "pickup_date": str(date.today() + timedelta(days=1)),
        "delivery_date": str(date.today() + timedelta(days=3)),
        "target_price": 50000.00
    }
    res = api_client.post('/api/v1/loads/', payload, format='json')
    assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_unverified_transporter_bid_rejected(api_client, shipper_user, pending_transporter_user):
    """3. Unverified (PENDING) transporter attempting to submit a bid receives 403 Forbidden."""
    # Post load as shipper
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Modjo Container Freight",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Containers",
        weight_tonnes=30.00,
        pickup_date=date.today() + timedelta(days=2),
        delivery_date=date.today() + timedelta(days=4),
        target_price=90000.00,
        status=LoadStatus.POSTED
    )

    api_client.force_authenticate(user=pending_transporter_user)
    bid_payload = {
        "amount": 88000.00,
        "notes": "Fast transit"
    }
    res = api_client.post(f'/api/v1/loads/{load.id}/bids/', bid_payload, format='json')
    assert res.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_verified_transporter_can_submit_bid(api_client, shipper_user, verified_transporter_user, transporter_vehicle):
    """5. VERIFIED transporter submits competitive bid with valid fleet vehicle."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Modjo Container Freight",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Containers",
        weight_tonnes=30.00,
        pickup_date=date.today() + timedelta(days=2),
        delivery_date=date.today() + timedelta(days=4),
        target_price=90000.00,
        status=LoadStatus.POSTED
    )

    api_client.force_authenticate(user=verified_transporter_user)
    bid_payload = {
        "proposed_vehicle": transporter_vehicle.id,
        "amount": 85000.00,
        "notes": "Ready for pickup at Djibouti Port Gate 3."
    }
    res = api_client.post(f'/api/v1/loads/{load.id}/bids/', bid_payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert float(data['amount']) == 85000.00
    assert data['status'] == "SUBMITTED"


@pytest.mark.django_db
def test_transporter_cannot_bid_with_other_transporter_vehicle(api_client, shipper_user, verified_transporter_user, transporter_vehicle2):
    """6. Transporter proposing another transporter's vehicle gets 400 Bad Request."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Modjo Cargo",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Steel",
        weight_tonnes=25.00,
        pickup_date=date.today() + timedelta(days=2),
        delivery_date=date.today() + timedelta(days=4),
        target_price=70000.00
    )

    api_client.force_authenticate(user=verified_transporter_user)
    bid_payload = {
        "proposed_vehicle": transporter_vehicle2.id, # Belongs to verified_transporter_user2
        "amount": 68000.00
    }
    res = api_client.post(f'/api/v1/loads/{load.id}/bids/', bid_payload, format='json')
    assert res.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_atomic_bid_acceptance_workflow(api_client, shipper_user, verified_transporter_user, verified_transporter_user2, transporter_vehicle, transporter_vehicle2):
    """
    9. ATOMIC BID ACCEPTANCE WORKFLOW:
    - Transporter 1 submits Bid 1 (120,000 ETB).
    - Transporter 2 submits Bid 2 (115,000 ETB).
    - Shipper accepts Bid 2.
    - Asserts winning Bid 2 -> ACCEPTED, competing Bid 1 -> REJECTED, Load -> ASSIGNED with winning transporter and vehicle.
    """
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="High Priority Fertilizer Shipment",
        origin="Djibouti Port",
        destination="Mekelle Hub",
        cargo_type="Fertilizer",
        weight_tonnes=40.00,
        pickup_date=date.today() + timedelta(days=3),
        delivery_date=date.today() + timedelta(days=7),
        target_price=130000.00,
        status=LoadStatus.POSTED
    )

    # Transporter 1 bids 120,000 ETB
    bid1 = Bid.objects.create(
        load=load,
        transporter=verified_transporter_user.transporter_profile,
        proposed_vehicle=transporter_vehicle,
        amount=120000.00,
        status=BidStatus.SUBMITTED
    )

    # Transporter 2 bids 115,000 ETB
    bid2 = Bid.objects.create(
        load=load,
        transporter=verified_transporter_user2.transporter_profile,
        proposed_vehicle=transporter_vehicle2,
        amount=115000.00,
        status=BidStatus.SUBMITTED
    )

    # Shipper accepts Bid 2
    api_client.force_authenticate(user=shipper_user)
    res = api_client.post(f'/api/v1/bids/{bid2.id}/accept/')
    assert res.status_code == status.HTTP_200_OK

    load.refresh_from_db()
    bid1.refresh_from_db()
    bid2.refresh_from_db()

    # Verify atomic state updates
    assert load.status == LoadStatus.ASSIGNED
    assert load.assigned_transporter == verified_transporter_user2.transporter_profile
    assert load.assigned_vehicle == transporter_vehicle2

    assert bid2.status == BidStatus.ACCEPTED
    assert bid1.status == BidStatus.REJECTED


@pytest.mark.django_db
def test_transporter_can_withdraw_bid(api_client, shipper_user, verified_transporter_user, transporter_vehicle):
    """10. Transporter can withdraw their pending submitted bid."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Coffee Export Shipment",
        origin="Addis Ababa",
        destination="Djibouti Port",
        cargo_type="Coffee Beans",
        weight_tonnes=20.00,
        pickup_date=date.today() + timedelta(days=2),
        delivery_date=date.today() + timedelta(days=4),
        target_price=60000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(
        load=load,
        transporter=verified_transporter_user.transporter_profile,
        proposed_vehicle=transporter_vehicle,
        amount=58000.00,
        status=BidStatus.SUBMITTED
    )

    api_client.force_authenticate(user=verified_transporter_user)
    res = api_client.post(f'/api/v1/bids/{bid.id}/withdraw/')
    assert res.status_code == status.HTTP_200_OK
    bid.refresh_from_db()
    assert bid.status == BidStatus.WITHDRAWN


@pytest.mark.django_db
def test_shipper_can_cancel_unassigned_load(api_client, shipper_user):
    """11. Shipper can cancel a posted unassigned cargo load."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="General Freight",
        origin="Dire Dawa",
        destination="Djibouti Port",
        cargo_type="Textiles",
        weight_tonnes=15.00,
        pickup_date=date.today() + timedelta(days=2),
        delivery_date=date.today() + timedelta(days=4),
        target_price=45000.00,
        status=LoadStatus.POSTED
    )

    api_client.force_authenticate(user=shipper_user)
    res = api_client.post(f'/api/v1/loads/{load.id}/cancel/')
    assert res.status_code == status.HTTP_200_OK
    load.refresh_from_db()
    assert load.status == LoadStatus.CANCELLED


@pytest.mark.django_db
def test_load_filtering_by_corridor(api_client, shipper_user):
    """12. Filter spot market loads by corridor origin, destination, and vehicle type."""
    CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Load 1",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Wheat",
        weight_tonnes=30.00,
        required_vehicle_type=VehicleType.FLATBED,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=80000.00,
        status=LoadStatus.POSTED
    )
    CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Load 2",
        origin="Addis Ababa",
        destination="Hawassa",
        cargo_type="Manufactured",
        weight_tonnes=10.00,
        required_vehicle_type=VehicleType.CONTAINER_TRUCK,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=30000.00,
        status=LoadStatus.POSTED
    )

    api_client.force_authenticate(user=shipper_user)
    res = api_client.get('/api/v1/loads/?origin=Djibouti&required_vehicle_type=FLATBED')
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    results = data['results'] if isinstance(data, dict) and 'results' in data else data
    assert len(results) == 1
    assert results[0]['origin'] == "Djibouti Port"
