import time
from decimal import Decimal
from datetime import timedelta
import pytest

from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import Role, ShipperProfile, TransporterProfile, DriverProfile
from apps.marketplace.models import (
    CargoLoad, LoadStatus, Shipment, ShipmentStatus, Vehicle,
    DriverIncidentReport, IncidentType,
    Route, RouteStatus, RouteDeviationStatus, LocationUpdate,
    PredictionRecord, PredictionType, RiskLevel,
    PriceRecommendation, MarketPressure,
    AutomationRule, AutomationRuleType, RecommendationPriority,
    AutomationRecommendation, RecommendationStatus, AutomationExecution,
    OperationalEvent, OperationalEventType, EventSeverity,
    Notification
)
from apps.marketplace.command_center_services import OperationalCommandCenterService

User = get_user_model()


@pytest.fixture
def admin_user(db):
    user = User.objects.filter(email="admin_phase15@tradeflow.et").first()
    if not user:
        user = User.objects.create_superuser(email="admin_phase15@tradeflow.et", password="Password123!", role=Role.ADMIN)
    return user


@pytest.fixture
def shipper_user(db):
    user = User.objects.filter(email="shipper_phase15@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="shipper_phase15@tradeflow.et", password="Password123!", role=Role.SHIPPER)
        ShipperProfile.objects.get_or_create(
            user=user,
            defaults={
                "company_name": "Djibouti Freight Hub PLC",
                "trade_license_number": "TL-SHIP-15",
                "tax_id": "TIN-SHIP-15"
            }
        )
    return user


@pytest.fixture
def transporter_user(db):
    user = User.objects.filter(email="transporter_phase15@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="transporter_phase15@tradeflow.et", password="Password123!", role=Role.TRANSPORTER)
        TransporterProfile.objects.get_or_create(
            user=user,
            defaults={
                "company_name": "Rift Valley Fleet Services",
                "trade_license_number": "TL-RIFT-15",
                "tax_id": "TIN-RIFT-15",
                "verification_status": "VERIFIED"
            }
        )
    return user


@pytest.fixture
def driver_user(db, transporter_user):
    user = User.objects.filter(email="driver_phase15@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="driver_phase15@tradeflow.et", password="Password123!", role=Role.DRIVER)
        DriverProfile.objects.get_or_create(
            user=user,
            defaults={
                "transporter": transporter_user.transporter_profile,
                "license_number": "DL-ETH-1515"
            }
        )
    return user


@pytest.fixture
def unrelated_user(db):
    user = User.objects.filter(email="unrelated_phase15@tradeflow.et").first()
    if not user:
        user = User.objects.create_user(email="unrelated_phase15@tradeflow.et", password="Password123!", role=Role.SHIPPER)
    return user


@pytest.fixture
def active_shipment(db, shipper_user, transporter_user, driver_user):
    load = CargoLoad.objects.create(
        shipper=shipper_user.shipper_profile,
        title="Command Center Freight #15",
        origin="Addis Ababa",
        destination="Djibouti Port",
        weight_tonnes=Decimal("30.00"),
        target_price=Decimal("150000.00"),
        pickup_date=timezone.now().date() + timedelta(days=1),
        delivery_date=timezone.now().date() + timedelta(days=4),
        status=LoadStatus.ASSIGNED
    )

    vehicle = Vehicle.objects.create(
        transporter=transporter_user.transporter_profile,
        plate_number="ETH-1515",
        vehicle_type="TRAILER_TRUCK",
        capacity_tonnes=Decimal("40.00")
    )

    shipment = Shipment.objects.create(
        load=load,
        transporter=transporter_user.transporter_profile,
        driver=driver_user.driver_profile,
        vehicle=vehicle,
        tracking_number="TRK-20260822-0015-CMD",
        status=ShipmentStatus.IN_TRANSIT,
        origin="Addis Ababa",
        destination="Djibouti Port"
    )

    # Route
    Route.objects.create(
        shipment=shipment,
        origin="Addis Ababa",
        destination="Djibouti Port",
        total_distance_km=Decimal("910.00"),
        estimated_duration_hours=Decimal("18.50"),
        status=RouteStatus.ACTIVE,
        is_active=True
    )


    return shipment


@pytest.mark.django_db
class TestCommandCenterSummaryAndHealth:
    def test_get_realtime_summary(self, active_shipment, admin_user):
        summary = OperationalCommandCenterService.get_realtime_summary(admin_user)
        assert summary["total_active_shipments"] >= 1
        assert "shipments_at_risk" in summary
        assert "active_incidents" in summary
        assert "unread_notifications" in summary
        assert "generated_at" in summary

    def test_operational_health_score_healthy(self, admin_user):
        health = OperationalCommandCenterService.calculate_operational_health_score(admin_user)
        assert 0.0 <= health["score"] <= 100.0
        assert health["level"] in ["HEALTHY", "STABLE", "WARNING", "CRITICAL", "SEVERE"]
        assert isinstance(health["factors"], list)

    def test_operational_health_score_with_critical_incidents(self, active_shipment, driver_user, admin_user):
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.ACCIDENT,
            description="Collided with stationary barrier",
            reported_at=timezone.now()
        )

        health = OperationalCommandCenterService.calculate_operational_health_score(admin_user)
        assert health["score"] > 0.0
        assert any(f["factor"] == "critical_incidents" for f in health["factors"])

    def test_health_score_boundaries(self, admin_user):
        health = OperationalCommandCenterService.calculate_operational_health_score(admin_user)
        assert 0 <= health["score"] <= 100


@pytest.mark.django_db
class TestShipmentAttentionQueue:
    def test_attention_queue_ranking(self, active_shipment, driver_user, admin_user):
        # Create incident
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.VEHICLE_BREAKDOWN,
            description="Engine malfunction",
            reported_at=timezone.now()
        )

        queue = OperationalCommandCenterService.get_shipments_requiring_attention(admin_user)
        assert len(queue) >= 1
        item = queue[0]
        assert item["shipment_id"] == active_shipment.id
        assert item["priority"] in ["MEDIUM", "HIGH", "CRITICAL"]
        assert len(item["attention_reasons"]) >= 1


@pytest.mark.django_db
class TestAlertIntelligenceAndTrends:
    def test_alert_intelligence(self, active_shipment, admin_user):
        event = OperationalEvent.objects.create(
            event_type=OperationalEventType.ROUTE_DEVIATION,
            severity=EventSeverity.CRITICAL,
            shipment=active_shipment,
            title="Corridor Deviation",
            description="Vehicle off route",
            idempotency_key="cmd_test_key_001"
        )
        Notification.objects.create(
            event=event,
            recipient=admin_user,
            title=event.title,
            message=event.description
        )

        alerts = OperationalCommandCenterService.get_alert_intelligence(admin_user)
        assert alerts["total_alerts"] >= 1
        assert alerts["critical_alerts"] >= 1
        assert alerts["unacknowledged_critical_alerts"] >= 1

    def test_alert_trends(self, active_shipment, admin_user):
        trends_24h = OperationalCommandCenterService.get_alert_trends(admin_user, time_window="24h")
        assert trends_24h["period"] == "24h"
        assert isinstance(trends_24h["buckets"], list)

        trends_1h = OperationalCommandCenterService.get_alert_trends(admin_user, time_window="1h")
        assert trends_1h["period"] == "1h"


@pytest.mark.django_db
class TestRiskAndDomainIntelligence:
    def test_risk_distribution(self, active_shipment, admin_user):
        PredictionRecord.objects.create(
            shipment=active_shipment,
            prediction_type=PredictionType.OPERATIONAL_RISK,
            risk_score=Decimal("85.00"),
            risk_level=RiskLevel.CRITICAL,
            confidence_score=Decimal("0.90")
        )

        risk_dist = OperationalCommandCenterService.get_risk_distribution(admin_user)
        assert risk_dist["total_shipments_evaluated"] >= 1
        assert "CRITICAL" in risk_dist["distribution"]

    def test_incident_intelligence(self, active_shipment, driver_user, admin_user):
        DriverIncidentReport.objects.create(
            shipment=active_shipment,
            driver=driver_user.driver_profile,
            reported_by=driver_user,
            incident_type=IncidentType.ROAD_PROBLEM,
            description="Road block near Modjo",
            reported_at=timezone.now()
        )

        inc_intel = OperationalCommandCenterService.get_incident_intelligence(admin_user)
        assert inc_intel["total_active_incidents"] >= 1
        assert len(inc_intel["incidents_by_type"]) >= 1

    def test_route_and_telemetry_intelligence(self, active_shipment, admin_user):
        route_intel = OperationalCommandCenterService.get_route_telemetry_intelligence(admin_user)
        assert "shipments_currently_deviated" in route_intel
        assert "stale_gps_shipment_count" in route_intel

    def test_market_pricing_intelligence(self, active_shipment, admin_user):
        from apps.marketplace.pricing_services import DynamicPricingService
        DynamicPricingService.generate_price_recommendation(active_shipment)

        market_intel = OperationalCommandCenterService.get_market_pricing_intelligence(admin_user)
        assert "high_market_pressure_count" in market_intel
        assert market_intel["average_pricing_confidence"] > 0.0


    def test_automation_workflow_intelligence(self, active_shipment, admin_user):
        rule = AutomationRule.objects.create(
            name="Rule 15",
            rule_type=AutomationRuleType.HIGH_OPERATIONAL_RISK,
            priority=RecommendationPriority.CRITICAL
        )
        AutomationRecommendation.objects.create(
            shipment=active_shipment,
            rule=rule,
            recommendation_type="REVIEW_SHIPMENT",
            priority=RecommendationPriority.CRITICAL,
            status=RecommendationStatus.PENDING,
            title="High Operational Risk",
            description="Review shipment"
        )

        auto_intel = OperationalCommandCenterService.get_automation_workflow_intelligence(admin_user)
        assert auto_intel["pending_recommendations"] >= 1
        assert auto_intel["critical_pending_recommendations"] >= 1


@pytest.mark.django_db
class TestEventCorrelationAndUnifiedSummary:
    def test_event_correlation(self, active_shipment):
        corr = OperationalCommandCenterService.correlate_shipment_events(active_shipment)
        assert corr["shipment_id"] == active_shipment.id
        assert corr["correlation_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
        assert len(corr["correlation_key"]) > 0


    def test_unified_shipment_summary(self, active_shipment, admin_user):
        summary = OperationalCommandCenterService.get_unified_shipment_operational_summary(active_shipment.id, admin_user)
        assert summary["shipment"]["id"] == active_shipment.id
        assert "risk" in summary
        assert "route" in summary
        assert "event_correlation" in summary


@pytest.mark.django_db
class TestRESTAPIsAndAuthorization:
    def test_command_center_endpoints_authorized(self, active_shipment, admin_user):
        client = APIClient()
        client.force_authenticate(user=admin_user)

        endpoints = [
            "/api/v1/operations/dashboard/",
            "/api/v1/operations/health/",
            "/api/v1/operations/attention/",
            "/api/v1/operations/alerts/",
            "/api/v1/operations/alerts/trends/",
            "/api/v1/operations/risk-distribution/",
            "/api/v1/operations/incidents/",
            "/api/v1/operations/telemetry/",
            "/api/v1/operations/market/",
            "/api/v1/operations/automation/",
            f"/api/v1/operations/shipments/{active_shipment.id}/summary/"
        ]

        for ep in endpoints:
            res = client.get(ep)
            assert res.status_code == status.HTTP_200_OK

    def test_unauthenticated_api_access_rejected(self):
        client = APIClient()
        res = client.get("/api/v1/operations/dashboard/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_participant_isolation(self, active_shipment, shipper_user, unrelated_user):
        client = APIClient()

        # Shipper participant access to their own shipment summary -> 200
        client.force_authenticate(user=shipper_user)
        res = client.get(f"/api/v1/operations/shipments/{active_shipment.id}/summary/")
        assert res.status_code == status.HTTP_200_OK

        # Unrelated user access to shipment summary -> 404
        client.force_authenticate(user=unrelated_user)
        res = client.get(f"/api/v1/operations/shipments/{active_shipment.id}/summary/")
        assert res.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
class TestNonMutationGuarantees:
    def test_command_center_does_not_mutate_state(self, active_shipment, admin_user):
        orig_status = active_shipment.status

        client = APIClient()
        client.force_authenticate(user=admin_user)

        client.get("/api/v1/operations/dashboard/")
        client.get("/api/v1/operations/health/")
        client.get("/api/v1/operations/attention/")
        client.get(f"/api/v1/operations/shipments/{active_shipment.id}/summary/")

        active_shipment.refresh_from_db()
        assert active_shipment.status == orig_status
