import pytest
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, Role, TransporterProfile, DriverProfile, ShipperProfile
from apps.marketplace.models import (
    Vehicle, VehicleType, FuelType, CargoLoad, LoadStatus, Shipment, ShipmentStatus,
    LocationUpdate, DriverIncidentReport, IncidentType, Route, RouteWaypoint,
    PredictiveModel, PredictionRecord, PredictionType, RiskLevel
)
from apps.marketplace.predictive_services import (
    ETADelayPredictionService, ShipmentRiskPredictionService, RouteRiskPredictionService,
    FuelPredictionService, IncidentRiskPredictionService, OperationalRiskService,
    PredictiveModelRegistryService
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email='admin_p11@tradeflow.et',
        password='password123',
        role=Role.ADMIN,
        is_staff=True,
        is_superuser=True
    )


@pytest.fixture
def shipper_user(db):
    user = User.objects.create_user(
        email='shipper_p11@tradeflow.et',
        password='password123',
        role=Role.SHIPPER
    )
    ShipperProfile.objects.create(user=user, company_name='Ethiopia Grain Enterprise')
    return user


@pytest.fixture
def transporter_user(db):
    user = User.objects.create_user(
        email='transporter_p11@tradeflow.et',
        password='password123',
        role=Role.TRANSPORTER
    )
    TransporterProfile.objects.create(user=user, company_name='Awash Freight Logistics')
    return user


@pytest.fixture
def driver_user(db, transporter_user):
    user = User.objects.create_user(
        email='driver_p11@tradeflow.et',
        password='password123',
        role=Role.DRIVER
    )
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number='ET-DRV-777',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )
    return user


@pytest.fixture
def unauthorized_user(db, transporter_user):
    user = User.objects.create_user(
        email='unassigned_p11@tradeflow.et',
        password='password123',
        role=Role.DRIVER
    )
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number='ET-DRV-666',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )
    return user


@pytest.fixture
def active_shipment(db, shipper_user, transporter_user, driver_user):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title='Wheat Freight Addis to Modjo',
        origin='Addis Ababa',
        destination='Modjo Dry Port',
        weight_tonnes=Decimal('30.00'),
        required_vehicle_type=VehicleType.FLATBED,
        pickup_date=timezone.now().date(),
        delivery_date=timezone.now().date() + timedelta(days=2),
        target_price=Decimal('85000.00'),
        status=LoadStatus.ASSIGNED
    )
    vehicle = Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number='ET-3-7777',
        vehicle_type=VehicleType.FLATBED,
        capacity_tonnes=Decimal('35.00'),
        fuel_type=FuelType.DIESEL
    )
    shipment = Shipment.objects.create(
        tracking_number='TRK-P11-TEST-0001',
        load=load,
        transporter=transporter_user.transporter_profile,
        vehicle=vehicle,
        driver=driver_user.driver_profile,
        status=ShipmentStatus.IN_TRANSIT,
        origin='Addis Ababa',
        destination='Modjo Dry Port'
    )

    # Attach Active Route with waypoints
    route = Route.objects.create(
        shipment=shipment,
        origin='Addis Ababa',
        destination='Modjo Dry Port',
        total_distance_km=Decimal('63.40'),
        estimated_duration_hours=Decimal('1.27'),
        estimated_arrival_time=timezone.now() + timedelta(hours=2),
        average_speed_kmh=Decimal('50.00'),
        is_active=True
    )
    RouteWaypoint.objects.create(route=route, sequence=1, location_name='Addis Kality', latitude=Decimal('9.0300'), longitude=Decimal('38.7400'))
    RouteWaypoint.objects.create(route=route, sequence=2, location_name='Modjo Dry Port', latitude=Decimal('8.6000'), longitude=Decimal('39.1200'))

    return shipment


@pytest.mark.django_db
class TestRiskLevelScoringLogic:
    def test_risk_level_from_score_boundaries(self):
        assert RiskLevel.from_score(0) == RiskLevel.LOW
        assert RiskLevel.from_score(24) == RiskLevel.LOW
        assert RiskLevel.from_score(25) == RiskLevel.MEDIUM
        assert RiskLevel.from_score(49) == RiskLevel.MEDIUM
        assert RiskLevel.from_score(50) == RiskLevel.HIGH
        assert RiskLevel.from_score(74) == RiskLevel.HIGH
        assert RiskLevel.from_score(75) == RiskLevel.CRITICAL
        assert RiskLevel.from_score(100) == RiskLevel.CRITICAL

    def test_risk_level_out_of_bounds_clamping(self):
        assert RiskLevel.from_score(-50) == RiskLevel.LOW
        assert RiskLevel.from_score(999) == RiskLevel.CRITICAL


@pytest.mark.django_db
class TestPredictiveModelRegistry:
    def test_get_or_create_default_model(self):
        model_obj = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.ETA_DELAY)
        assert model_obj.name == "TradeFlow Baseline ETA Predictor"
        assert model_obj.version == "1.0"
        assert model_obj.is_active is True

        # Re-fetching returns exact same instance
        model_obj_2 = PredictiveModelRegistryService.get_or_create_default_model(PredictionType.ETA_DELAY)
        assert model_obj.id == model_obj_2.id


@pytest.mark.django_db
class TestPredictiveServicesDomainLogic:
    def test_eta_delay_prediction(self, active_shipment, driver_user):
        LocationUpdate.objects.create(
            shipment=active_shipment,
            latitude=Decimal('9.0300'),
            longitude=Decimal('38.7400'),
            recorded_by=driver_user,
            timestamp=timezone.now()
        )
        res = ETADelayPredictionService.predict_eta_delay(active_shipment)
        assert res['prediction_available'] is True
        assert 'predicted_delay_minutes' in res
        assert 0.0 <= res['delay_probability'] <= 1.0
        assert res['risk_level'] in RiskLevel.values
        assert PredictionRecord.objects.filter(shipment=active_shipment, prediction_type=PredictionType.ETA_DELAY).exists()

    def test_eta_delay_prediction_insufficient_data(self, db, shipper_user, transporter_user, driver_user):
        # Empty shipment without route or GPS
        load = CargoLoad.objects.create(
            shipper=shipper_user.shipper_profile,
            title='Empty Cargo',
            origin='A', destination='B',
            weight_tonnes=10,
            required_vehicle_type=VehicleType.FLATBED,
            pickup_date=timezone.now().date(),
            delivery_date=timezone.now().date() + timedelta(days=1),
            target_price=10000,
            status=LoadStatus.ASSIGNED
        )
        vehicle = Vehicle.objects.create(
            transporter=transporter_user.transporter_profile,
            plate_number='ET-3-9999',
            vehicle_type=VehicleType.FLATBED,
            capacity_tonnes=Decimal('30.00'),
            fuel_type=FuelType.DIESEL
        )
        empty_shipment = Shipment.objects.create(
            tracking_number='TRK-EMPTY-001',
            load=load,
            transporter=transporter_user.transporter_profile,
            vehicle=vehicle,
            status=ShipmentStatus.CREATED,
            origin='A',
            destination='B'
        )
        res = ETADelayPredictionService.predict_eta_delay(empty_shipment)
        assert res['prediction_available'] is False
        assert "Insufficient" in res['reason']

    def test_shipment_risk_prediction(self, active_shipment, driver_user):
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.CHECKPOINT_DELAY,
            description='Customs clearance delay at Mojo Checkpoint',
            reported_at=timezone.now()
        )
        res = ShipmentRiskPredictionService.predict_shipment_risk(active_shipment)
        assert res['prediction_available'] is True
        assert res['risk_score'] > 20
        assert len(res['explanation']) > 0

    def test_route_risk_prediction(self, active_shipment):
        res = RouteRiskPredictionService.predict_route_risk(active_shipment)
        assert res['prediction_available'] is True
        assert res['risk_score'] >= 10

    def test_fuel_prediction(self, active_shipment):
        res = FuelPredictionService.predict_fuel_consumption(active_shipment, fuel_efficiency=3.5, fuel_price=65.0)
        assert res['prediction_available'] is True
        assert res['predicted_fuel_liters'] > 10.0
        assert res['predicted_fuel_cost_etb'] > 500.0

    def test_incident_risk_prediction(self, active_shipment, driver_user):
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.ROAD_PROBLEM,
            description='Potholes near Kality',
            reported_at=timezone.now()
        )
        res = IncidentRiskPredictionService.predict_incident_risk(active_shipment)
        assert res['prediction_available'] is True
        assert res['risk_score'] >= 30

    def test_operational_risk_composite(self, active_shipment):
        res = OperationalRiskService.get_composite_dashboard(active_shipment)
        assert 'overall_risk' in res
        assert 'eta' in res
        assert 'route' in res
        assert 'fuel' in res
        assert 'incident' in res
        assert 'deviation' in res
        assert 0 <= res['overall_risk']['score'] <= 100


@pytest.mark.django_db
class TestPredictiveIntelligenceRESTEndpoints:
    def test_get_dashboard_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data['shipment_id'] == active_shipment.id
        assert 'overall_risk' in res.data

    def test_get_eta_prediction_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/eta/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data['prediction_type'] == PredictionType.ETA_DELAY

    def test_get_shipment_risk_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/risk/")
        assert res.status_code == status.HTTP_200_OK
        assert 'explanation' in res.data

    def test_get_route_risk_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/route-risk/")
        assert res.status_code == status.HTTP_200_OK
        assert 'major_risk_factors' in res.data

    def test_get_fuel_prediction_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/fuel/?fuel_efficiency=3.5&fuel_price=65.0")
        assert res.status_code == status.HTTP_200_OK
        assert res.data['predicted_fuel_liters'] > 0.0

    def test_get_incident_risk_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/incident-risk/")
        assert res.status_code == status.HTTP_200_OK
        assert 'risk_factors' in res.data

    def test_get_prediction_history_api(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        # Generate prediction records first
        OperationalRiskService.get_composite_dashboard(active_shipment)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/history/")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) >= 1

    def test_unauthorized_user_access_rejected(self, api_client, active_shipment, unauthorized_user):
        api_client.force_authenticate(user=unauthorized_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/")
        assert res.status_code == status.HTTP_403_FORBIDDEN

    def test_unauthenticated_request_rejected(self, api_client, active_shipment):
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_predictions_do_not_mutate_shipment_state(self, api_client, active_shipment, driver_user):
        initial_status = active_shipment.status
        api_client.force_authenticate(user=driver_user)
        api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/")
        api_client.get(f"/api/v1/shipments/{active_shipment.id}/predictions/risk/")
        active_shipment.refresh_from_db()
        assert active_shipment.status == initial_status

    def test_client_cannot_manipulate_risk_score_in_body(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        # GET request ignores posted body
        res = api_client.get(
            f"/api/v1/shipments/{active_shipment.id}/predictions/risk/",
            data={"risk_score": 0, "risk_level": "LOW"},
            format='json'
        )
        assert res.status_code == status.HTTP_200_OK
        # Risk score is derived server-side
        assert isinstance(res.data['risk_score'], int)
