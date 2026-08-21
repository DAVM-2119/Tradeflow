import pytest
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, Role, TransporterProfile, DriverProfile, ShipperProfile
from apps.marketplace.models import (
    Vehicle, VehicleType, FuelType, CargoLoad, LoadStatus, Bid, BidStatus, Shipment, ShipmentStatus,
    LocationUpdate, DriverIncidentReport, IncidentType, Route, RouteWaypoint, RouteRecalculation,
    RouteStatus, RouteDeviationStatus
)
from apps.marketplace.services import RouteOptimizationService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email='admin_p10@tradeflow.et',
        password='password123',
        role=Role.ADMIN,
        is_staff=True,
        is_superuser=True
    )


@pytest.fixture
def shipper_user(db):
    user = User.objects.create_user(
        email='shipper_p10@tradeflow.et',
        password='password123',
        role=Role.SHIPPER
    )
    ShipperProfile.objects.create(user=user, company_name='Ethiopian Trading Enterprise')
    return user


@pytest.fixture
def transporter_user(db):
    user = User.objects.create_user(
        email='transporter_p10@tradeflow.et',
        password='password123',
        role=Role.TRANSPORTER
    )
    TransporterProfile.objects.create(user=user, company_name='Mojo Express Freight Ltd')
    return user


@pytest.fixture
def driver_user(db, transporter_user):
    user = User.objects.create_user(
        email='driver_p10@tradeflow.et',
        password='password123',
        role=Role.DRIVER
    )
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number='ET-DRV-999',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )
    return user


@pytest.fixture
def unassigned_user(db, transporter_user):
    user = User.objects.create_user(
        email='unassigned_p10@tradeflow.et',
        password='password123',
        role=Role.DRIVER
    )
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number='ET-DRV-888',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )
    return user


@pytest.fixture
def active_shipment(db, shipper_user, transporter_user, driver_user):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title='Coffee Cargo Addis to Djibouti',
        origin='Addis Ababa',
        destination='Djibouti Port',
        weight_tonnes=Decimal('25.00'),
        required_vehicle_type=VehicleType.FLATBED,
        pickup_date=timezone.now().date(),
        delivery_date=timezone.now().date() + timedelta(days=3),
        target_price=Decimal('120000.00'),
        status=LoadStatus.ASSIGNED
    )
    vehicle = Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number='ET-3-8888',
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=Decimal('30.00'),
        fuel_type=FuelType.DIESEL
    )
    shipment = Shipment.objects.create(
        tracking_number='TRK-P10-TEST-0001',
        load=load,
        transporter=transporter_user.transporter_profile,
        vehicle=vehicle,
        driver=driver_user.driver_profile,
        status=ShipmentStatus.IN_TRANSIT,
        origin='Addis Ababa',
        destination='Djibouti Port'
    )
    return shipment


@pytest.mark.django_db
class TestRouteMathematicalCalculations:
    def test_haversine_distance_known_coordinates(self):
        # Addis Ababa (9.0300, 38.7400) to Mojo (8.6000, 39.1200) ~ 63.4 km
        dist = RouteOptimizationService.calculate_haversine_distance(
            9.0300, 38.7400, 8.6000, 39.1200
        )
        assert isinstance(dist, Decimal)
        assert 60.0 <= float(dist) <= 66.0

    def test_haversine_distance_same_coordinates(self):
        dist = RouteOptimizationService.calculate_haversine_distance(
            9.0300, 38.7400, 9.0300, 38.7400
        )
        assert dist == Decimal('0.00')

    def test_haversine_distance_boundary_coordinates(self):
        dist1 = RouteOptimizationService.calculate_haversine_distance(-90.0, -180.0, 90.0, 180.0)
        assert dist1 > Decimal('0.00')

        dist2 = RouteOptimizationService.calculate_haversine_distance(-90.0, 0.0, 90.0, 0.0)
        assert float(dist2) == pytest.approx(20015.08, abs=50.0)

    def test_haversine_distance_invalid_coordinates_rejected(self):
        with pytest.raises(Exception):
            RouteOptimizationService.calculate_haversine_distance(90.000001, 38.74, 8.60, 39.12)
        with pytest.raises(Exception):
            RouteOptimizationService.calculate_haversine_distance(9.03, -180.000001, 8.60, 39.12)
        with pytest.raises(Exception):
            RouteOptimizationService.calculate_haversine_distance("abc", "xyz", 8.60, 39.12)


@pytest.mark.django_db
class TestRouteServiceDomainLogic:
    def test_create_route_and_waypoints(self, active_shipment):
        waypoints_data = [
            {"sequence": 1, "location_name": "Addis Ababa Kality", "latitude": 9.0300, "longitude": 38.7400},
            {"sequence": 2, "location_name": "Mojo Toll Dry Port", "latitude": 8.6000, "longitude": 39.1200},
            {"sequence": 3, "location_name": "Awash Arba Checkpoint", "latitude": 8.9800, "longitude": 40.1700},
            {"sequence": 4, "location_name": "Djibouti Port Gate", "latitude": 11.5880, "longitude": 43.1450},
        ]
        route = RouteOptimizationService.create_route(
            shipment=active_shipment,
            waypoints_data=waypoints_data,
            average_speed_kmh=Decimal('60.00')
        )
        assert route.is_active is True
        assert route.status == RouteStatus.ACTIVE
        assert route.waypoints.count() == 4
        assert float(route.total_distance_km) > 500.0
        assert route.estimated_arrival_time > timezone.now()

    def test_route_recalculation_preserves_history(self, active_shipment, admin_user):
        w1 = [
            {"sequence": 1, "location_name": "Addis Ababa", "latitude": 9.0300, "longitude": 38.7400},
            {"sequence": 2, "location_name": "Mojo", "latitude": 8.6000, "longitude": 39.1200},
        ]
        r1 = RouteOptimizationService.create_route(active_shipment, w1)
        assert r1.is_active is True

        w2 = [
            {"sequence": 1, "location_name": "Addis Ababa", "latitude": 9.0300, "longitude": 38.7400},
            {"sequence": 2, "location_name": "Adama Bypass", "latitude": 8.5400, "longitude": 39.2700},
            {"sequence": 3, "location_name": "Mojo Dry Port", "latitude": 8.6000, "longitude": 39.1200},
        ]
        recalc = RouteOptimizationService.recalculate_route(
            shipment=active_shipment,
            waypoints_data=w2,
            reason="Road blockage near Awash",
            triggered_by=admin_user
        )

        r1.refresh_from_db()
        assert r1.is_active is False
        assert r1.status == RouteStatus.SUPERSEDED
        assert recalc.previous_route == r1
        assert recalc.new_route.is_active is True
        assert recalc.reason == "Road blockage near Awash"

    def test_actual_gps_distance_calculation(self, active_shipment, driver_user):
        LocationUpdate.objects.create(shipment=active_shipment, latitude=Decimal('9.0300'), longitude=Decimal('38.7400'), recorded_by=driver_user, timestamp=timezone.now() - timedelta(minutes=60))
        LocationUpdate.objects.create(shipment=active_shipment, latitude=Decimal('8.6000'), longitude=Decimal('39.1200'), recorded_by=driver_user, timestamp=timezone.now() - timedelta(minutes=30))
        LocationUpdate.objects.create(shipment=active_shipment, latitude=Decimal('8.9800'), longitude=Decimal('40.1700'), recorded_by=driver_user, timestamp=timezone.now())

        dist = RouteOptimizationService.calculate_actual_gps_distance(active_shipment)
        assert float(dist) > 100.0

    def test_route_deviation_detection(self, active_shipment, driver_user):
        w = [
            {"sequence": 1, "location_name": "Addis Ababa", "latitude": 9.0300, "longitude": 38.7400},
            {"sequence": 2, "location_name": "Mojo", "latitude": 8.6000, "longitude": 39.1200},
        ]
        RouteOptimizationService.create_route(active_shipment, w)

        # Telemetry ping close to Mojo -> ON_ROUTE
        LocationUpdate.objects.create(shipment=active_shipment, latitude=Decimal('8.6010'), longitude=Decimal('39.1210'), recorded_by=driver_user, timestamp=timezone.now())
        dev1 = RouteOptimizationService.detect_route_deviation(active_shipment, threshold_km=Decimal('5.00'))
        assert dev1['status'] == RouteDeviationStatus.ON_ROUTE

        # Telemetry ping 100km away in Hawassa -> DEVIATED
        LocationUpdate.objects.create(shipment=active_shipment, latitude=Decimal('7.0500'), longitude=Decimal('38.4700'), recorded_by=driver_user, timestamp=timezone.now())
        dev2 = RouteOptimizationService.detect_route_deviation(active_shipment, threshold_km=Decimal('5.00'))
        assert dev2['status'] == RouteDeviationStatus.DEVIATED

    def test_fuel_analytics_calculation(self, active_shipment):
        w = [
            {"sequence": 1, "location_name": "P1", "latitude": 9.0300, "longitude": 38.7400},
            {"sequence": 2, "location_name": "P2", "latitude": 8.6000, "longitude": 39.1200},
        ]
        route = RouteOptimizationService.create_route(active_shipment, w)
        fuel = RouteOptimizationService.calculate_fuel_analytics(
            active_shipment,
            fuel_efficiency_km_per_liter=Decimal('3.50'),
            fuel_price_per_liter=Decimal('65.00')
        )
        assert fuel['planned_distance_km'] == route.total_distance_km
        assert float(fuel['planned_fuel_used_liters']) == pytest.approx(float(route.total_distance_km) / 3.5, abs=0.5)
        assert float(fuel['planned_fuel_cost_etb']) == pytest.approx(float(fuel['planned_fuel_used_liters']) * 65.0, abs=5.0)


@pytest.mark.django_db
class TestRouteOptimizationEndpoints:
    def test_create_and_get_route_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        url = f"/api/v1/shipments/{active_shipment.id}/route/"

        payload = {
            "origin": "Addis Ababa Kality Terminal",
            "destination": "Djibouti Container Terminal",
            "average_speed_kmh": 55.00,
            "waypoints": [
                {"sequence": 1, "location_name": "Addis Ababa Kality", "latitude": 9.0300, "longitude": 38.7400},
                {"sequence": 2, "location_name": "Mojo Toll Plaza", "latitude": 8.6000, "longitude": 39.1200},
                {"sequence": 3, "location_name": "Djibouti Port", "latitude": 11.5880, "longitude": 43.1450}
            ]
        }

        # POST create route
        response = api_client.post(url, payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['is_active'] is True
        assert len(response.data['waypoints']) == 3

        # GET active route
        get_resp = api_client.get(url)
        assert get_resp.status_code == status.HTTP_200_OK
        assert get_resp.data['id'] == response.data['id']

    def test_route_recalculation_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        url_create = f"/api/v1/shipments/{active_shipment.id}/route/"
        payload = {
            "waypoints": [
                {"sequence": 1, "location_name": "A", "latitude": 9.03, "longitude": 38.74},
                {"sequence": 2, "location_name": "B", "latitude": 8.60, "longitude": 39.12}
            ]
        }
        api_client.post(url_create, payload, format='json')

        url_recalc = f"/api/v1/shipments/{active_shipment.id}/route/recalculate/"
        recalc_payload = {
            "reason": "Road maintenance delay on A1 highway",
            "waypoints": [
                {"sequence": 1, "location_name": "A", "latitude": 9.03, "longitude": 38.74},
                {"sequence": 2, "location_name": "B-Bypass", "latitude": 8.54, "longitude": 39.27},
                {"sequence": 3, "location_name": "C", "latitude": 8.60, "longitude": 39.12}
            ]
        }
        resp = api_client.post(url_recalc, recalc_payload, format='json')
        assert resp.status_code == status.HTTP_200_OK
        assert resp.data['reason'] == "Road maintenance delay on A1 highway"
        assert resp.data['new_route_id'] is not None

    def test_eta_fuel_analytics_deviation_endpoints(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)

        # Create active route first
        url_create = f"/api/v1/shipments/{active_shipment.id}/route/"
        payload = {
            "waypoints": [
                {"sequence": 1, "location_name": "Addis Ababa", "latitude": 9.0300, "longitude": 38.7400},
                {"sequence": 2, "location_name": "Mojo", "latitude": 8.6000, "longitude": 39.1200}
            ]
        }
        api_client.post(url_create, payload, format='json')

        # GET ETA
        eta_resp = api_client.get(f"/api/v1/shipments/{active_shipment.id}/eta/")
        assert eta_resp.status_code == status.HTTP_200_OK
        assert eta_resp.data['has_active_route'] is True

        # GET Fuel
        fuel_resp = api_client.get(f"/api/v1/shipments/{active_shipment.id}/fuel/?fuel_efficiency=3.5&fuel_price=65.0")
        assert fuel_resp.status_code == status.HTTP_200_OK
        assert float(fuel_resp.data['fuel_price_per_liter_etb']) == 65.0

        # GET Deviation
        dev_resp = api_client.get(f"/api/v1/shipments/{active_shipment.id}/deviation/")
        assert dev_resp.status_code == status.HTTP_200_OK
        assert 'status' in dev_resp.data

        # GET Route Analytics
        analytics_resp = api_client.get(f"/api/v1/shipments/{active_shipment.id}/route/analytics/")
        assert analytics_resp.status_code == status.HTTP_200_OK
        assert analytics_resp.data['tracking_number'] == active_shipment.tracking_number

    def test_unauthorized_user_access_rejected(self, api_client, active_shipment, unassigned_user):
        api_client.force_authenticate(user=unassigned_user)
        url = f"/api/v1/shipments/{active_shipment.id}/route/"
        response = api_client.get(url)
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_request_rejected(self, api_client, active_shipment):
        url = f"/api/v1/shipments/{active_shipment.id}/route/"
        response = api_client.get(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
