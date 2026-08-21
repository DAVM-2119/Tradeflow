import pytest
from datetime import date, timedelta
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.accounts.models import Role, VerificationStatus, ShipperProfile, TransporterProfile, DriverProfile
from apps.marketplace.models import (
    Vehicle,
    VehicleType,
    CargoLoad,
    LoadStatus,
    Bid,
    BidStatus,
    Shipment,
    ShipmentStatus,
    LocationUpdate,
    ShipmentMilestone,
)
from apps.marketplace.services import VerificationService, BiddingService, TrackingService

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user():
    return User.objects.create_superuser(email="admin_phase6@tradeflow.et", password="AdminPassword123!")


@pytest.fixture
def shipper_user():
    user = User.objects.create_user(email="shipper_phase6@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    ShipperProfile.objects.create(
        user=user,
        company_name="Ethiopia Coffee Export Enterprise",
        trade_license_number="TL-COFFEE-01",
        tax_id="TIN-COFFEE-01"
    )
    return user


@pytest.fixture
def transporter_user(admin_user):
    user = User.objects.create_user(email="transporter_phase6@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
    trans = TransporterProfile.objects.create(
        user=user,
        company_name="Djibouti Corridor Express",
        trade_license_number="TL-DJIB-01",
        tax_id="TIN-DJIB-01",
        verification_status=VerificationStatus.PENDING
    )
    VerificationService.verify_transporter(trans, admin_user, reason="Verified for Phase 6 shipment testing.")
    return user


@pytest.fixture
def driver_user(transporter_user):
    user = User.objects.create_user(email="driver_phase6@tradeflow.et", password="Password123!", role=Role.DRIVER)
    driver_profile = DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number="DL-ETH-992211"
    )
    return user


@pytest.fixture
def vehicle(transporter_user):
    return Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number="ET-3-66554",
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=45.00,
        insurance_policy_number="POL-665",
        roadworthiness_certificate="ROAD-665"
    )


@pytest.mark.django_db
def test_shipment_auto_created_on_bid_acceptance(shipper_user, transporter_user, vehicle):
    """1. Accepting a load bid automatically creates a Shipment record with TRK- tracking number and milestone."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Coffee Container Export",
        origin="Modjo Dry Port",
        destination="Djibouti Port",
        cargo_type="Coffee Beans",
        weight_tonnes=35.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=100000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(
        load=load,
        transporter=transporter_user.transporter_profile,
        proposed_vehicle=vehicle,
        amount=95000.00,
        status=BidStatus.SUBMITTED
    )

    # Shipper accepts bid
    BiddingService.accept_bid(shipper_user, bid)

    load.refresh_from_db()
    assert load.status == LoadStatus.ASSIGNED
    assert hasattr(load, 'shipment')

    shipment = load.shipment
    assert shipment.tracking_number.startswith("TRK-")
    assert shipment.status == ShipmentStatus.CREATED
    assert shipment.transporter == transporter_user.transporter_profile
    assert shipment.vehicle == vehicle

    # Verify initial milestone
    milestone = shipment.milestones.first()
    assert milestone.status == ShipmentStatus.CREATED


@pytest.mark.django_db
def test_transporter_can_assign_driver(api_client, shipper_user, transporter_user, driver_user, vehicle):
    """2. Transporter owner assigns a driver to shipment via API."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Bulk Import Cargo",
        origin="Djibouti Port",
        destination="Addis Ababa",
        cargo_type="Steel",
        weight_tonnes=40.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=4),
        target_price=130000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(
        load=load,
        transporter=transporter_user.transporter_profile,
        proposed_vehicle=vehicle,
        amount=125000.00,
        status=BidStatus.SUBMITTED
    )
    BiddingService.accept_bid(shipper_user, bid)
    shipment = load.shipment

    api_client.force_authenticate(user=transporter_user)
    payload = {"driver_id": driver_user.driver_profile.id}
    res = api_client.post(f'/api/v1/shipments/{shipment.id}/assign-driver/', payload, format='json')
    assert res.status_code == status.HTTP_200_OK
    assert res.json()['driver_name'] == driver_user.get_full_name()
    assert res.json()['status'] == "DRIVER_ASSIGNED"


@pytest.mark.django_db
def test_driver_can_update_shipment_status_lifecycle(api_client, shipper_user, transporter_user, driver_user, vehicle):
    """3 & 4. Assigned driver transitions status through lifecycle (AT_PICKUP -> IN_TRANSIT -> DELIVERED)."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Textile Shipment",
        origin="Hawassa Industrial Park",
        destination="Djibouti Port",
        cargo_type="Apparel",
        weight_tonnes=20.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=70000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(
        load=load,
        transporter=transporter_user.transporter_profile,
        proposed_vehicle=vehicle,
        amount=65000.00,
        status=BidStatus.SUBMITTED
    )
    BiddingService.accept_bid(shipper_user, bid)
    shipment = load.shipment
    TrackingService.assign_driver(shipment, driver_user.driver_profile, transporter_user)

    api_client.force_authenticate(user=driver_user)

    # 1. AT_PICKUP
    res1 = api_client.post(f'/api/v1/shipments/{shipment.id}/status/', {"status": "AT_PICKUP", "location_name": "Hawassa Gate 1"}, format='json')
    assert res1.status_code == status.HTTP_200_OK
    assert res1.json()['status'] == "AT_PICKUP"

    # 2. IN_TRANSIT
    res2 = api_client.post(f'/api/v1/shipments/{shipment.id}/status/', {"status": "IN_TRANSIT", "location_name": "Modjo Highway"}, format='json')
    assert res2.status_code == status.HTTP_200_OK
    assert res2.json()['status'] == "IN_TRANSIT"
    assert res2.json()['actual_pickup_time'] is not None

    # 3. DELIVERED
    res3 = api_client.post(f'/api/v1/shipments/{shipment.id}/status/', {"status": "DELIVERED", "location_name": "Djibouti Port Terminal 2"}, format='json')
    assert res3.status_code == status.HTTP_200_OK
    assert res3.json()['status'] == "DELIVERED"
    assert res3.json()['actual_delivery_time'] is not None


@pytest.mark.django_db
def test_driver_can_submit_gps_location_ping(api_client, shipper_user, transporter_user, driver_user, vehicle):
    """5. Driver submits GPS location telemetry pings."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Wheat Cargo",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Wheat",
        weight_tonnes=30.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=80000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(load=load, transporter=transporter_user.transporter_profile, proposed_vehicle=vehicle, amount=78000.00, status=BidStatus.SUBMITTED)
    BiddingService.accept_bid(shipper_user, bid)
    shipment = load.shipment
    TrackingService.assign_driver(shipment, driver_user.driver_profile, transporter_user)

    api_client.force_authenticate(user=driver_user)
    ping_payload = {
        "latitude": 11.5883000,
        "longitude": 43.1450000,
        "speed_kmh": 65.50,
        "heading_degrees": 240.00,
        "location_name": "Near Adama Toll Checkpoint"
    }
    res = api_client.post(f'/api/v1/shipments/{shipment.id}/location/', ping_payload, format='json')
    assert res.status_code == status.HTTP_201_CREATED
    assert float(res.json()['latitude']) == 11.5883000
    assert float(res.json()['speed_kmh']) == 65.50


@pytest.mark.django_db
def test_shipper_and_transporter_can_view_tracking_history(api_client, shipper_user, transporter_user, driver_user, vehicle):
    """6. Shipper and Transporter view complete GPS tracking history and milestone audit trail."""
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Industrial Machinery",
        origin="Djibouti Port",
        destination="Modjo Dry Port",
        cargo_type="Machinery",
        weight_tonnes=25.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=3),
        target_price=110000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(load=load, transporter=transporter_user.transporter_profile, proposed_vehicle=vehicle, amount=105000.00, status=BidStatus.SUBMITTED)
    BiddingService.accept_bid(shipper_user, bid)
    shipment = load.shipment
    TrackingService.assign_driver(shipment, driver_user.driver_profile, transporter_user)
    TrackingService.record_location(shipment, 11.58, 43.14, speed_kmh=70.0, location_name="En-route Corridor", user=driver_user)

    # Shipper views tracking
    api_client.force_authenticate(user=shipper_user)
    res = api_client.get(f'/api/v1/shipments/{shipment.id}/tracking/')
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data['tracking_number'] == shipment.tracking_number
    assert len(data['milestones']) >= 2
    assert len(data['location_updates']) == 1


@pytest.mark.django_db
def test_unauthorized_user_rejected(api_client, shipper_user, transporter_user, vehicle):
    """7. User not participating in shipment gets 403 Forbidden on tracking updates."""
    other_user = User.objects.create_user(email="unauth_user@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    ShipperProfile.objects.create(user=other_user, company_name="Other PLC", trade_license_number="TL-OTH-99", tax_id="TIN-OTH-99")

    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Private Cargo",
        origin="Addis",
        destination="Modjo",
        cargo_type="Goods",
        weight_tonnes=10.00,
        pickup_date=date.today() + timedelta(days=1),
        delivery_date=date.today() + timedelta(days=2),
        target_price=30000.00,
        status=LoadStatus.POSTED
    )
    bid = Bid.objects.create(load=load, transporter=transporter_user.transporter_profile, proposed_vehicle=vehicle, amount=28000.00, status=BidStatus.SUBMITTED)
    BiddingService.accept_bid(shipper_user, bid)
    shipment = load.shipment

    api_client.force_authenticate(user=other_user)
    res = api_client.get(f'/api/v1/shipments/{shipment.id}/tracking/')
    assert res.status_code == status.HTTP_403_FORBIDDEN
