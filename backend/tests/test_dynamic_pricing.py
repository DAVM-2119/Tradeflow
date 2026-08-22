import pytest
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import User, Role, TransporterProfile, DriverProfile, ShipperProfile
from apps.marketplace.models import (
    Vehicle, VehicleType, FuelType, CargoLoad, LoadStatus, Bid, BidStatus, Shipment, ShipmentStatus,
    LocationUpdate, Route, RouteWaypoint, RouteDeviationStatus, PricingStrategy, PriceRecommendation,
    PricingMarketSnapshot, MarketPressure, RiskLevel
)
from apps.marketplace.pricing_services import DynamicPricingService


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        email='admin_p12@tradeflow.et',
        password='password123',
        role=Role.ADMIN,
        is_staff=True,
        is_superuser=True
    )


@pytest.fixture
def shipper_user(db):
    user = User.objects.create_user(
        email='shipper_p12@tradeflow.et',
        password='password123',
        role=Role.SHIPPER
    )
    ShipperProfile.objects.create(user=user, company_name='Ethiopia Coffee Export Corp')
    return user


@pytest.fixture
def transporter_user(db):
    user = User.objects.create_user(
        email='transporter_p12@tradeflow.et',
        password='password123',
        role=Role.TRANSPORTER
    )
    TransporterProfile.objects.create(
        user=user,
        company_name='Red Sea Transport PLC',
        verification_status='VERIFIED'
    )
    return user


@pytest.fixture
def driver_user(db, transporter_user):
    user = User.objects.create_user(
        email='driver_p12@tradeflow.et',
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
def unauthorized_user(db, transporter_user):
    user = User.objects.create_user(
        email='unassigned_p12@tradeflow.et',
        password='password123',
        role=Role.DRIVER
    )
    DriverProfile.objects.create(
        user=user,
        transporter=transporter_user.transporter_profile,
        license_number='ET-DRV-555',
        license_expiration=timezone.now().date() + timedelta(days=365)
    )
    return user


@pytest.fixture
def active_shipment(db, shipper_user, transporter_user, driver_user):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title='Coffee Beans Addis to Djibouti',
        origin='Addis Ababa',
        destination='Djibouti Port',
        weight_tonnes=Decimal('28.50'),
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
        capacity_tonnes=Decimal('35.00'),
        fuel_type=FuelType.DIESEL
    )
    shipment = Shipment.objects.create(
        tracking_number='TRK-P12-TEST-0001',
        load=load,
        transporter=transporter_user.transporter_profile,
        vehicle=vehicle,
        driver=driver_user.driver_profile,
        status=ShipmentStatus.IN_TRANSIT,
        origin='Addis Ababa',
        destination='Djibouti Port'
    )

    # Active Route
    route = Route.objects.create(
        shipment=shipment,
        origin='Addis Ababa',
        destination='Djibouti Port',
        total_distance_km=Decimal('560.40'),
        estimated_duration_hours=Decimal('11.20'),
        estimated_arrival_time=timezone.now() + timedelta(hours=12),
        average_speed_kmh=Decimal('50.00'),
        is_active=True
    )
    RouteWaypoint.objects.create(route=route, sequence=1, location_name='Addis Ababa', latitude=Decimal('9.0300'), longitude=Decimal('38.7400'))
    RouteWaypoint.objects.create(route=route, sequence=2, location_name='Djibouti Port', latitude=Decimal('11.5883'), longitude=Decimal('43.1450'))

    return shipment


@pytest.mark.django_db
class TestPricingStrategyModel:
    def test_get_or_create_default_pricing_strategy(self):
        strategy = DynamicPricingService.get_or_create_default_pricing_strategy()
        assert strategy.name == "TradeFlow Standard Corridor Strategy"
        assert strategy.version == "1.0"
        assert strategy.is_active is True
        assert strategy.base_rate_per_km == Decimal('50.00')

    def test_unique_strategy_name_and_version(self, db):
        PricingStrategy.objects.create(name="Custom Strategy", version="1.0", base_rate_per_km=Decimal('60.00'))
        with pytest.raises(Exception):
            PricingStrategy.objects.create(name="Custom Strategy", version="1.0", base_rate_per_km=Decimal('70.00'))


@pytest.mark.django_db
class TestPricingMathematics:
    def test_base_price_calculation(self, active_shipment):
        strategy = DynamicPricingService.get_or_create_default_pricing_strategy()
        dist, base_price = DynamicPricingService.calculate_base_price(active_shipment, strategy)
        assert dist == Decimal('560.40')
        # 560.40 * 50.00 = 28020.00
        assert base_price == Decimal('28020.00')

    def test_price_recommendation_bounds_and_decimal_precision(self, active_shipment):
        res = DynamicPricingService.generate_price_recommendation(active_shipment)
        assert res['recommendation_available'] is True
        assert isinstance(res['recommended_price_etb'], Decimal)
        assert res['minimum_price_etb'] <= res['recommended_price_etb'] <= res['maximum_price_etb']
        assert res['recommended_price_etb'] > Decimal('0.00')

    def test_insufficient_data_handling_empty_shipment(self, db, shipper_user, transporter_user):
        load = CargoLoad.objects.create(
            shipper=shipper_user.shipper_profile,
            title='Cargo without Route',
            origin='', destination='',
            weight_tonnes=10, required_vehicle_type=VehicleType.FLATBED,
            pickup_date=timezone.now().date(), delivery_date=timezone.now().date() + timedelta(days=1),
            target_price=10000, status=LoadStatus.ASSIGNED
        )
        vehicle = Vehicle.objects.create(
            transporter=transporter_user.transporter_profile,
            plate_number='ET-3-0000', vehicle_type=VehicleType.FLATBED,
            capacity_tonnes=Decimal('30.00'), fuel_type=FuelType.DIESEL
        )
        empty_shipment = Shipment.objects.create(
            tracking_number='TRK-NOROUTE-001',
            load=load, transporter=transporter_user.transporter_profile,
            vehicle=vehicle, status=ShipmentStatus.CREATED, origin='', destination=''
        )

        res = DynamicPricingService.generate_price_recommendation(empty_shipment)
        assert res['recommendation_available'] is False
        assert "Insufficient" in res['reason']
        assert res['recommended_price_etb'] == Decimal('0.00')


@pytest.mark.django_db
class TestMarketIntelligence:
    def test_market_snapshot_calculation(self, active_shipment):
        snapshot = DynamicPricingService.calculate_market_snapshot(active_shipment)
        assert snapshot.origin_region == "Addis Ababa"
        assert snapshot.destination_region == "Djibouti Port"
        assert snapshot.market_pressure in MarketPressure.values
        assert PricingMarketSnapshot.objects.filter(id=snapshot.id).exists()

    def test_get_market_intelligence_api_service(self, active_shipment):
        intel = DynamicPricingService.get_market_intelligence(active_shipment)
        assert intel['shipment_id'] == active_shipment.id
        assert intel['market_data_available'] is True
        assert 'demand_score' in intel
        assert 'supply_score' in intel


@pytest.mark.django_db
class TestRecommendationPersistence:
    def test_price_recommendation_auditing_and_ordering(self, active_shipment):
        rec1 = DynamicPricingService.generate_price_recommendation(active_shipment)
        rec2 = DynamicPricingService.generate_price_recommendation(active_shipment)

        history = list(DynamicPricingService.get_pricing_history(active_shipment))
        assert len(history) == 2
        assert history[0].id == rec2['recommendation_id']
        assert history[1].id == rec1['recommendation_id']
        assert history[0].created_at >= history[1].created_at


@pytest.mark.django_db
class TestPricingRESTAPI:
    def test_get_price_recommendation_endpoint(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data['recommendation_available'] is True
        assert 'recommended_price_etb' in res.data
        assert 'factors' in res.data

    def test_get_pricing_history_endpoint(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        DynamicPricingService.generate_price_recommendation(active_shipment)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/history/")
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) >= 1

    def test_get_market_intelligence_endpoint(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/market/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data['market_data_available'] is True

    def test_admin_list_pricing_strategies_endpoint(self, api_client, admin_user, driver_user):
        DynamicPricingService.get_or_create_default_pricing_strategy()

        # Non-admin rejected
        api_client.force_authenticate(user=driver_user)
        res_user = api_client.get("/api/v1/pricing/strategies/")
        assert res_user.status_code == status.HTTP_403_FORBIDDEN

        # Admin allowed
        api_client.force_authenticate(user=admin_user)
        res_admin = api_client.get("/api/v1/pricing/strategies/")
        assert res_admin.status_code == status.HTTP_200_OK
        assert len(res_admin.data) >= 1

    def test_unauthorized_and_unauthenticated_access(self, api_client, active_shipment, unauthorized_user):
        # Unauthenticated
        res_unauth = api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/")
        assert res_unauth.status_code == status.HTTP_401_UNAUTHORIZED

        # Non-participant
        api_client.force_authenticate(user=unauthorized_user)
        res_unassigned = api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/")
        assert res_unassigned.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestSecurityAndNonMutation:
    def test_invalid_strategy_id_rejected(self, api_client, active_shipment, driver_user):
        api_client.force_authenticate(user=driver_user)
        res = api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/?strategy_id=999999")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_pricing_generation_does_not_mutate_business_state(self, api_client, active_shipment, driver_user):
        initial_status = active_shipment.status
        initial_target_price = active_shipment.load.target_price

        api_client.force_authenticate(user=driver_user)
        api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/")
        api_client.get(f"/api/v1/shipments/{active_shipment.id}/pricing/market/")

        active_shipment.refresh_from_db()
        assert active_shipment.status == initial_status
        assert active_shipment.load.target_price == initial_target_price
